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

_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z`])")
_ABBREVIATIONS = ("e.g.", "i.e.")

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
    text: str  # whitespace collapsed, list marker dropped
    start_line: int
    end_line: int


def code_tokens(description: str) -> list[str]:
    """Distinct code-shaped names in order of appearance: identifiers in backtick spans (a
    trailing `()` dropped), and outside them dotted names whose segments are at least two
    characters long, names with an underscore, and CamelCase names."""
    found: list[tuple[int, str]] = []
    for match in _SPAN.finditer(description):
        name = match.group(1).strip().removesuffix("()")
        if _DOTTED.fullmatch(name):
            found.append((match.start(), name))
    masked = _SPAN.sub(lambda match: " " * len(match.group()), description)
    for match in _NAME.finditer(masked):
        name = match.group()
        if "." in name:
            if all(len(segment) >= 2 for segment in name.split(".")):
                found.append((match.start(), name))
        elif "_" in name or _CAMEL.search(name):
            found.append((match.start(), name))
    return list(dict.fromkeys(name for _, name in sorted(found)))


def sentences(text: str, first_line: int) -> list[Sentence]:
    """The sentences of a section body whose first line is `first_line`. Fenced code is
    skipped; a blank line, a list item or a table row starts a new unit; a unit is split
    after `.`, `!` or `?` followed by a capital letter or a backtick, except after `e.g.`
    and `i.e.`."""
    units: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []

    def close() -> None:
        nonlocal current
        if current:
            units.append(current)
        current = []

    for offset, line in enumerate(outside_fences(text).split("\n")):
        number = first_line + offset
        stripped = line.strip()
        if not stripped:
            close()
        elif stripped.startswith("|"):
            close()
            if re.search(r"\w", stripped):  # a separator row has no words
                units.append([(number, stripped)])
        elif item := _LIST_ITEM.match(line):
            close()
            current = [(number, item.group(1).strip())]
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
    prefer, else `related`. Whole words, ignoring case; forbids wins over encourages."""
    if _NEGATED.search(sentence):
        return "related"
    if _FORBIDS.search(sentence):
        return "forbids"
    if _ENCOURAGES.search(sentence):
        return "encourages"
    return "related"
