"""Split a Markdown file into one chunk per heading.

A line-based reader for the CommonMark block rules that decide what is a heading: ATX
headings (`# Title`, up to three leading spaces), setext headings (a paragraph underlined with
`===` or `---`, unless a line of it starts a list item, quote, table row or HTML), and the places a
heading cannot be: fenced code (``` or ~~~), indented code, HTML comments and YAML front
matter at the top of the file. Each heading starts a chunk that runs to the next heading of
any level. Text before the first heading is a chunk with an empty anchor.

Anchors are the heading's plain text (links reduced to their visible text; code and emphasis
markers and inline HTML dropped); a heading repeated in one file gets ` (2)`, ` (3)` in its
anchor only.
Line numbers are 1-based, and only `\n`, `\r\n` and `\r` end a line.
"""

import re
from dataclasses import dataclass

_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*))?$")
_FENCE = re.compile(r"^ {0,3}(?:(`{3,})(?!.*`)|(~{3,}))")  # no backtick after a ``` opener
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_THEMATIC_BREAK = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
# A paragraph with a line that starts a list item, quote, table row or HTML never becomes a
# heading: that line starts or interrupts it
_NOT_SETEXT_TEXT = re.compile(r"^ {0,3}(?:[-*+][ \t]|\d+[.)][ \t]|>|\||<)")
_COMMENT_START = re.compile(r"^ {0,3}<!--")
_NEWLINE = re.compile(r"\r\n|\r|\n")

_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_IMAGE_OR_LINK = re.compile(r"!?\[([^\]]*)\](?:\([^)]*\)|\[[^\]]*\])")
_SHORTCUT_LINK = re.compile(r"!?\[([^\]]*)\](?![(\[])")
_HTML_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
_EMPHASIS = (
    re.compile(r"\*\*(.+?)\*\*"),
    re.compile(r"(?<!\w)__(.+?)__(?!\w)"),
    re.compile(r"\*(.+?)\*"),
    re.compile(r"(?<!\w)_(.+?)_(?!\w)"),
)


@dataclass(frozen=True, kw_only=True)
class Chunk:
    anchor: str
    heading_path: str  # the headings above this one and its own, joined by " > "
    text: str  # the body Markdown, heading line excluded, outer blank lines trimmed
    start_line: int  # the heading line (for the preamble, its first non-blank line)
    end_line: int  # the last non-blank line


@dataclass(frozen=True)
class _Heading:
    first: int  # 0-based index of the heading's first line
    last: int  # 0-based index of its last line (the underline, for setext)
    level: int
    raw: str


# Helper: splits text into lines exactly as an editor numbers them, so cited line numbers are right.
def split_lines(text: str) -> list[str]:
    """Lines as an editor numbers them: only `\n`, `\r\n` and `\r` end a line."""
    lines = _NEWLINE.split(text)
    return lines[:-1] if lines[-1] == "" else lines


# Splits one Markdown file into sections at its headings; each Chunk has its heading path ('A > B >
# C'), a unique anchor, its text and exact line range.
def chunk(text: str) -> list[Chunk]:
    lines = split_lines(text)
    start = _body_start(lines)
    headings = _headings(lines, start)

    chunks: list[Chunk] = []
    used: set[str] = set()
    preamble_end = headings[0].first if headings else len(lines)
    body = _trimmed(lines, start, preamble_end)
    if body is not None:
        first, last = body
        chunks.append(_chunk("", "", lines, first, last, first, last))
        used.add("")

    stack: list[tuple[int, str]] = []
    for position, heading in enumerate(headings):
        plain = plain_heading(heading.raw)
        while stack and stack[-1][0] >= heading.level:
            stack.pop()
        stack.append((heading.level, plain))
        anchor = _unique(plain, used)
        used.add(anchor)
        end = headings[position + 1].first if position + 1 < len(headings) else len(lines)
        body = _trimmed(lines, heading.last + 1, end)
        first, last = body if body is not None else (heading.last + 1, heading.last)
        path = " > ".join(name for _, name in stack)
        chunks.append(_chunk(anchor, path, lines, heading.first, last, first, last))
    return chunks


# Helper for chunk: heading text as a reader sees it (links, code and emphasis markers removed).
def plain_heading(raw: str) -> str:
    """Heading text as a reader sees it: `[text](url)` gives `text`, code and emphasis
    markers are dropped (code span content stays literal), whitespace is collapsed."""
    text = _CLOSING_HASHES.sub("", raw.strip())
    text = _IMAGE_OR_LINK.sub(r"\1", text)
    parts: list[str] = []
    position = 0
    for match in _CODE_SPAN.finditer(text):
        parts.append(_prose(text[position : match.start()]))
        parts.append(match.group(2))
        position = match.end()
    parts.append(_prose(text[position:]))
    return " ".join("".join(parts).split())


# Helper: the text with fenced code blocks blanked out (lines kept, so numbering holds). Used by
# mentions.py.
def outside_fences(text: str) -> str:
    """The text with every line of fenced code, fence lines included, blanked out."""
    kept: list[str] = []
    fence: str | None = None
    for line in split_lines(text):
        if fence is not None:
            if _closes(fence, line):
                fence = None
            kept.append("")
        elif match := _FENCE.match(line):
            fence = match.group(1) or match.group(2)
            kept.append("")
        else:
            kept.append(line)
    return "\n".join(kept)


# Helper: True if a line closes the current ``` or ~~~ code fence.
def _closes(fence: str, line: str) -> bool:
    """A closing fence: at most 3 spaces of indent, at least as many of the same character,
    and nothing else."""
    stripped = line.strip()
    return _indent(line) <= 3 and stripped.startswith(fence) and set(stripped) == {fence[0]}


# Helper for plain_heading: strips links, inline HTML and emphasis from heading text outside code
# spans.
def _prose(text: str) -> str:
    """Heading text outside code spans: shortcut links and inline HTML reduced, emphasis
    markers dropped."""
    text = _HTML_TAG.sub("", _SHORTCUT_LINK.sub(r"\1", text))
    for pattern in _EMPHASIS:
        text = pattern.sub(r"\1", text)
    return text


# Helper for chunk: skips YAML front matter at the top of a file.
def _body_start(lines: list[str]) -> int:
    """Index of the first line after YAML front matter, or 0 when there is none."""
    if not lines or lines[0].strip() != "---":
        return 0
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            return index + 1
    return 0  # never closed: not front matter


# Helper for chunk: finds every heading (# style and underlined style), ignoring code fences, HTML
# comments and indented code.
def _headings(lines: list[str], start: int) -> list[_Heading]:
    headings: list[_Heading] = []
    fence: str | None = None
    in_comment = False
    in_paragraph = False
    paragraph_start = 0
    paragraph_can_be_heading = False
    for index in range(start, len(lines)):
        line = lines[index]
        if fence is not None:
            if _closes(fence, line):
                fence = None
            continue
        if in_comment:
            in_comment = "-->" not in line
            continue
        if match := _FENCE.match(line):
            fence = match.group(1) or match.group(2)
            in_paragraph = False
            continue
        if _COMMENT_START.match(line):
            in_comment = "-->" not in line[line.index("<!--") + 2 :]  # `<!-->` closes too
            in_paragraph = False
            continue
        if not line.strip():
            in_paragraph = False
            continue
        if in_paragraph and paragraph_can_be_heading and _SETEXT.match(line):
            level = 1 if line.strip().startswith("=") else 2
            raw = " ".join(lines[paragraph_start:index])
            headings.append(_Heading(paragraph_start, index, level, raw))
            in_paragraph = False
            continue
        if _THEMATIC_BREAK.match(line):
            in_paragraph = False
            continue
        if not in_paragraph and _indent(line) >= 4:
            continue  # indented code
        if match := _ATX.match(line):
            headings.append(_Heading(index, index, len(match.group(1)), match.group(2) or ""))
            in_paragraph = False
            continue
        if not in_paragraph:
            in_paragraph = True
            paragraph_start = index
            paragraph_can_be_heading = True
        if _NOT_SETEXT_TEXT.match(line):  # starts or interrupts the paragraph
            paragraph_can_be_heading = False
    return headings


# Helper: how many spaces a line is indented (tabs count as 4).
def _indent(line: str) -> int:
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


# Helper for chunk: first and last non-blank line in a range, or None.
def _trimmed(lines: list[str], start: int, end: int) -> tuple[int, int] | None:
    """First and last non-blank line indexes in lines[start:end], or None if all blank."""
    filled = [index for index in range(start, end) if lines[index].strip()]
    return (filled[0], filled[-1]) if filled else None


# Helper for chunk: builds one Chunk with 1-based line numbers.
def _chunk(
    anchor: str, path: str, lines: list[str], start: int, end: int, first: int, last: int
) -> Chunk:
    return Chunk(
        anchor=anchor,
        heading_path=path,
        text="\n".join(lines[first : last + 1]),
        start_line=start + 1,
        end_line=max(end, start) + 1,
    )


# Helper for chunk: makes repeated heading anchors unique ('Setup (2)').
def _unique(anchor: str, used: set[str]) -> str:
    if anchor not in used:
        return anchor
    counter = 2
    while f"{anchor} ({counter})" in used:
        counter += 1
    return f"{anchor} ({counter})"
