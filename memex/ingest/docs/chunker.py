"""Split a Markdown file into one chunk per heading.

A line-based reader for the CommonMark block rules that decide what is a heading: ATX
headings (`# Title`, up to three leading spaces), setext headings (a paragraph line underlined
with `===` or `---`), and the places a heading cannot be: fenced code (``` or ~~~), indented
code, and YAML front matter at the top of the file. Each heading starts a chunk that runs to
the next heading of any level. Text before the first heading is a chunk with an empty anchor.

Anchors are the heading's plain text (links reduced to their visible text, code and emphasis
markers dropped); a heading repeated in one file gets ` (2)`, ` (3)` in its anchor only.
Line numbers are 1-based.
"""

import re
from dataclasses import dataclass

_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*))?$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_THEMATIC_BREAK = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_NOT_SETEXT_TEXT = re.compile(r"^ {0,3}(?:[-*+][ \t]|\d+[.)][ \t]|>|\|)")  # list, quote, table

_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_IMAGE_OR_LINK = re.compile(r"!?\[([^\]]*)\](?:\([^)]*\)|\[[^\]]*\])")
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
    first: int  # 0-based index of the heading text line
    last: int  # 0-based index of its last line (the underline, for setext)
    level: int
    raw: str


def chunk(text: str) -> list[Chunk]:
    lines = text.splitlines()
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


def plain_heading(raw: str) -> str:
    """Heading text as a reader sees it: `[text](url)` gives `text`, code and emphasis
    markers are dropped (code span content stays literal), whitespace is collapsed."""
    text = _CLOSING_HASHES.sub("", raw.strip())
    text = _IMAGE_OR_LINK.sub(r"\1", text)
    parts: list[str] = []
    position = 0
    for match in _CODE_SPAN.finditer(text):
        parts.append(_without_emphasis(text[position : match.start()]))
        parts.append(match.group(2))
        position = match.end()
    parts.append(_without_emphasis(text[position:]))
    return " ".join("".join(parts).split())


def outside_fences(text: str) -> str:
    """The text with every line of fenced code, fence lines included, blanked out."""
    kept: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        if fence is not None:
            if _closes(fence, line):
                fence = None
            kept.append("")
        elif match := _FENCE.match(line):
            fence = match.group(1)
            kept.append("")
        else:
            kept.append(line)
    return "\n".join(kept)


def _closes(fence: str, line: str) -> bool:
    """A closing fence: at least as many of the same character, and nothing else."""
    stripped = line.strip()
    return stripped.startswith(fence) and set(stripped) == {fence[0]}


def _without_emphasis(text: str) -> str:
    for pattern in _EMPHASIS:
        text = pattern.sub(r"\1", text)
    return text


def _body_start(lines: list[str]) -> int:
    """Index of the first line after YAML front matter, or 0 when there is none."""
    if not lines or lines[0].strip() != "---":
        return 0
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            return index + 1
    return 0  # never closed: not front matter


def _headings(lines: list[str], start: int) -> list[_Heading]:
    headings: list[_Heading] = []
    fence: str | None = None
    in_paragraph = False
    paragraph_can_be_heading = False
    for index in range(start, len(lines)):
        line = lines[index]
        if fence is not None:
            if _closes(fence, line):
                fence = None
            continue
        if match := _FENCE.match(line):
            fence = match.group(1)
            in_paragraph = False
            continue
        if not line.strip():
            in_paragraph = False
            continue
        if in_paragraph and paragraph_can_be_heading and _SETEXT.match(line):
            level = 1 if line.strip().startswith("=") else 2
            headings.append(_Heading(index - 1, index, level, lines[index - 1]))
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
        in_paragraph = True
        paragraph_can_be_heading = not _NOT_SETEXT_TEXT.match(line)
    return headings


def _indent(line: str) -> int:
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def _trimmed(lines: list[str], start: int, end: int) -> tuple[int, int] | None:
    """First and last non-blank line indexes in lines[start:end], or None if all blank."""
    filled = [index for index in range(start, end) if lines[index].strip()]
    return (filled[0], filled[-1]) if filled else None


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


def _unique(anchor: str, used: set[str]) -> str:
    if anchor not in used:
        return anchor
    counter = 2
    while f"{anchor} ({counter})" in used:
        counter += 1
    return f"{anchor} ({counter})"
