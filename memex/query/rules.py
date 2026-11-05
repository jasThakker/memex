"""Text rules behind check_change (DESIGN.md section 10). Pure functions, no database.

- `code_tokens`: the code-shaped names in a change description, which check_change resolves
  against the graph. Plain English words are never tokens.
- `sentences`: a doc section body split into sentences, each with its own line range, so a
  guideline cites exactly the lines it quotes.
- `stance`: whether a sentence forbids or encourages something, from modal verbs only.
"""

import re
from bisect import bisect_right
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from memex.ingest.docs.chunker import outside_fences

Stance = Literal["forbids", "encourages", "related"]

_SPAN = re.compile(r"`([^`\n]+)`")
_DOTTED = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_NAME = re.compile(r"(?<![\w.])" + _DOTTED.pattern)
_CAMEL = re.compile(r"[a-z][A-Z]|[A-Z]{2}[a-z]")
_ACRONYM_PLURAL = re.compile(r"[A-Z]{2,}s")  # APIs, URLs, PRs
# Last segments that make a dotted word a file name or a host, not a code name.
_FILE_SUFFIXES = frozenset(
    "py pyi md rst txt toml cfg ini json yaml yml lock html css js ts sh com org io net".split()  # noqa: SIM905
)

_QUOTE_MARKER = re.compile(r"^\s*(?:>\s?)+")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$")
# A break after . ! or ? when the next sentence starts with a capital or a code span,
# possibly behind emphasis, a link bracket, a quote or a parenthesis.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[*_\[\"'(]*[A-Z`])")
_ABBREVIATIONS = ("e.g.", "i.e.")

_EMPHASIS = re.compile(r"\*+|(?<!\w)_+|_+(?!\w)")
_APOSTROPHE = "['’]"
_NEGATED = re.compile(
    rf"\b(?:don{_APOSTROPHE}t|do not|no) need to\b|\bnot (?:required|necessary)\b", re.I
)
_FORBIDS = re.compile(
    rf"\b(?:never|do not|don{_APOSTROPHE}t|must not|should not|shouldn{_APOSTROPHE}t|avoid)\b",
    re.I,
)
_ENCOURAGES = re.compile(r"\b(?:must|should|always|prefer)\b", re.I)


@dataclass(frozen=True)
class Sentence:
    text: str  # whitespace collapsed, list and quote markers dropped
    start_line: int
    end_line: int


def code_tokens(description: str) -> list[str]:
    """Distinct code-shaped names in order of appearance: a backtick span holding a dotted
    name (a trailing `()` dropped), and elsewhere, also inside other spans, dotted names whose
    segments are at least two characters long, names with an underscore, and CamelCase names.
    File names, hosts (`main.py`, `github.com`) and acronym plurals (`APIs`) are skipped."""
    found: list[tuple[int, str]] = []
    masked = description
    for match in _SPAN.finditer(description):
        name = match.group(1).strip().removesuffix("()")
        if _DOTTED.fullmatch(name):
            found.append((match.start(), name))
            masked = masked[: match.start()] + " " * len(match.group()) + masked[match.end() :]
    for match in _NAME.finditer(masked):
        name = match.group()
        if "." in name:
            segments = name.split(".")
            if all(len(s) >= 2 for s in segments) and segments[-1] not in _FILE_SUFFIXES:
                found.append((match.start(), name))
        elif not _ACRONYM_PLURAL.fullmatch(name) and ("_" in name or _CAMEL.search(name)):
            found.append((match.start(), name))
    return list(dict.fromkeys(name for _, name in sorted(found)))


def section_sentences(text: str, end_line: int) -> list[Sentence]:
    """The sentences of a stored doc section body. `text` is trimmed of outer blank lines
    and ends on `end_line`, so its first line is `end_line` minus its line breaks."""
    if not text:
        return []
    return sentences(text, first_line=end_line - text.count("\n"))


def sentences(text: str, first_line: int) -> list[Sentence]:
    """The sentences of a section body whose first line is `first_line`. Fenced code is
    skipped and blockquote markers dropped. A blank line, a list item or a table row starts
    a new unit (a table is found by its separator row, with or without outer pipes, and
    ends at a blank line or a list item). A unit
    is split after `.`, `!` or `?` followed by a sentence start (see _SENTENCE_BREAK),
    except after `e.g.` and `i.e.`."""
    units: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    in_table = False

    def close() -> None:
        nonlocal current
        if current:
            units.append(current)
        current = []

    for offset, raw in enumerate(outside_fences(text).split("\n")):
        number = first_line + offset
        line = _QUOTE_MARKER.sub("", raw)
        stripped = line.strip()
        if not stripped:
            close()
            in_table = False
        elif _TABLE_SEPARATOR.match(line):
            if current:  # the header row, read as a paragraph line until now
                header = current.pop()
                close()
                units.append([header])
            in_table = True
        elif item := _LIST_ITEM.match(line):  # also ends a table
            close()
            in_table = False
            current = [(number, item.group(1).strip())]
        elif in_table or stripped.startswith("|"):
            close()
            if re.search(r"\w", stripped):
                units.append([(number, stripped)])
        else:
            current.append((number, stripped))
    close()
    return [sentence for unit in units for sentence in _split(unit)]


def _split(unit: list[tuple[int, str]]) -> list[Sentence]:
    """A unit's lines joined with spaces and cut at sentence breaks."""
    starts: list[int] = []  # offset in `joined` where each line begins
    joined = ""
    for _, content in unit:
        starts.append(len(joined))
        joined += content + " "
    cuts = [0]
    for match in _SENTENCE_BREAK.finditer(joined):
        if not joined[: match.start()].lower().endswith(_ABBREVIATIONS):
            cuts.append(match.end())
    cuts.append(len(joined))

    result: list[Sentence] = []
    for start, end in pairwise(cuts):
        piece = joined[start:end]
        if not piece.strip():
            continue
        last = start + len(piece.rstrip()) - 1
        result.append(
            Sentence(
                text=" ".join(piece.split()),
                start_line=unit[bisect_right(starts, start) - 1][0],
                end_line=unit[bisect_right(starts, last) - 1][0],
            )
        )
    return result


def stance(sentence: str) -> Stance:
    """`related` for a negated requirement ("you don't need to"), else `forbids` for never,
    do not, must not, should not or avoid, else `encourages` for must, should, always or
    prefer, else `related`. Whole words, ignoring case and emphasis markers (`must **not**`);
    forbids wins over encourages."""
    return _decide(sentence)[0]


def modal_word(sentence: str) -> str:
    """The words that decided the sentence's stance, or "" when it is `related`."""
    return _decide(sentence)[1]


def _decide(sentence: str) -> tuple[Stance, str]:
    plain = _EMPHASIS.sub("", sentence)
    if _NEGATED.search(plain):
        return "related", ""
    if match := _FORBIDS.search(plain):
        return "forbids", match.group()
    if match := _ENCOURAGES.search(plain):
        return "encourages", match.group()
    return "related", ""
