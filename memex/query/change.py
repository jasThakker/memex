"""check_change (DESIGN.md section 10, ADR-002): which code a proposed change affects and
which documented rules apply. No LLM: the calling agent makes the final judgment.

- Symbols: the proposal's explicit `symbols` (stripped, empty ones skipped), or else the
  code-shaped names in its description (`rules.code_tokens`); at most MAX_TOKENS of them.
  Each goes through the symbol rule: one match is resolved, several are listed as ambiguous
  with at most MAX_CANDIDATES candidates (never guessed), none is unresolved.
- Affected: one impact walk from the start sets of all resolved symbols, AFFECTED_DEPTH
  edges deep, counted by layer (None last).
- Guidelines from doc sections that MENTION a symbol in that walk (the resolved symbols,
  their members and their dependents) or a module enclosing a resolved symbol (its module
  and the packages above it, the top-level package excluded, so its layer counts). Ranked as
  impact_of ranks docs: those on a resolved symbol first, then on a member or an enclosing
  module, then by the closest dependent, then by path and line. In each section, the
  sentences naming a mentioned symbol (see _names), or if none does (the mention is in the
  heading or a fence) those with a stance; those with a stance first.
- Then guidelines from a full-text search on the description: the best SEARCH_SECTIONS
  sections, and in each the sentences sharing a content word with the description (four
  letters or more, not a number or a common English word), those with a stance first, then
  those sharing more words.
- Each guideline quotes one sentence, centered on what matched, and cites its own lines. A
  sentence found both ways is listed once, as a mention. At most PER_SECTION per section
  and MAX_GUIDELINES in all.
- `truncated` is set when names, candidates or guidelines were cut.
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from neo4j import Driver, RoutingControl

from memex.graph.model import code_id
from memex.query.docs import MAX_QUERY_CHARS, search_sections, snippet
from memex.query.impact import start_set, walk
from memex.query.models import (
    AmbiguousName,
    ChangeCheck,
    ChangeProposal,
    Citation,
    Guideline,
    ImpactSummary,
    LayerCount,
    SymbolRef,
)
from memex.query.rules import Sentence, code_tokens, modal_word, section_sentences, stance
from memex.query.symbols import resolve_symbol

MAX_TOKENS = 10
MAX_CANDIDATES = 5
AFFECTED_DEPTH = 3
MAX_GUIDELINES = 6
PER_SECTION = 2
SEARCH_SECTIONS = 5

_WORD = re.compile(r"\w+")
_SPAN = re.compile(r"`([^`\n]+)`")
# Common words a description and a rule share without being about the same thing.
_STOPWORDS = frozenset(
    "about after also always avoid been before could does each from have into just like more "  # noqa: SIM905
    "must need never only other prefer should some such than that their them then there these "
    "they this those want were what when where which will with would your".split()
)

_MODULES = "MATCH (m:Module {codebase: $codebase}) WHERE m.id IN $ids RETURN m.id AS id"
_MENTIONING = (
    "MATCH (doc:Doc {codebase: $codebase})-[:MENTIONS]->(c) WHERE c.id IN $ids "
    "WITH DISTINCT doc "
    "MATCH (doc)-[:MENTIONS]->(m) WHERE m.id IN $ids "
    "RETURN properties(doc) AS props, "
    "collect([m.id, labels(m)[0], m.qualname, m.path]) AS mentions"
)


@dataclass(frozen=True)
class _Section:
    """A doc section's candidate sentences, best first, each with the text to center its
    quote on."""

    props: dict[str, Any]
    matched_on: str
    picks: list[tuple[Sentence, str]]


def check_change(driver: Driver, codebase: str, proposal: ChangeProposal) -> ChangeCheck:
    """The symbols a proposal names, what depends on them, and the rules that apply."""
    description = proposal.description.strip()
    if not description:
        raise ValueError("description must not be empty")
    if len(description) > MAX_QUERY_CHARS:
        raise ValueError(
            f"description must be at most {MAX_QUERY_CHARS} characters, got {len(description)}"
        )
    explicit = [symbol.strip() for symbol in proposal.symbols if symbol.strip()]
    names = list(dict.fromkeys(explicit)) or code_tokens(description)
    truncated = len(names) > MAX_TOKENS

    resolved: dict[str, SymbolRef] = {}
    ambiguous: list[AmbiguousName] = []
    unresolved: list[str] = []
    for name in names[:MAX_TOKENS]:
        ref, candidates, cut = resolve_symbol(driver, codebase, name, MAX_CANDIDATES)
        if ref is not None:
            resolved.setdefault(ref.qualname, ref)
        elif candidates:
            ambiguous.append(AmbiguousName(name=name, candidates=candidates))
            truncated = truncated or cut
        else:
            unresolved.append(name)

    resolved_ids = {code_id(codebase, qualname) for qualname in resolved}
    start_ids = [i for node_id in resolved_ids for i in start_set(driver, node_id)]
    distance, found = walk(driver, list(dict.fromkeys(start_ids)), AFFECTED_DEPTH)
    enclosing = _enclosing_modules(driver, codebase, list(resolved))
    searched = _search_sections(driver, codebase, description)
    guidelines, cut = _merge(
        _mention_sections(driver, codebase, resolved_ids, distance, enclosing)
        + searched[:SEARCH_SECTIONS]
    )
    cut = cut or any(section.picks for section in searched[SEARCH_SECTIONS:])

    return ChangeCheck(
        codebase=codebase,
        resolved_symbols=list(resolved.values()),
        ambiguous=ambiguous,
        unresolved=unresolved,
        affected=_summary(found),
        guidelines=guidelines[:MAX_GUIDELINES],
        truncated=truncated or cut or len(guidelines) > MAX_GUIDELINES,
    )


def _summary(found: list[Any]) -> ImpactSummary:
    """Dependents counted by layer, None last."""
    counts = Counter(dependent.symbol.layer for dependent in found)
    order = sorted(counts, key=lambda layer: (layer is None, layer or ""))
    return ImpactSummary(
        total=len(found), layers=[LayerCount(layer=layer, count=counts[layer]) for layer in order]
    )


def _enclosing_modules(driver: Driver, codebase: str, qualnames: list[str]) -> set[str]:
    """Ids of the modules and packages enclosing `qualnames`, the top-level package excluded."""
    ids = {
        code_id(codebase, ".".join(parts[:end]))
        for parts in (qualname.split(".") for qualname in qualnames)
        for end in range(2, len(parts))
    }
    if not ids:
        return set()
    rows, _, _ = driver.execute_query(
        _MODULES, codebase=codebase, ids=list(ids), routing_=RoutingControl.READ
    )
    return {row["id"] for row in rows}


def _mention_sections(
    driver: Driver,
    codebase: str,
    resolved_ids: set[str],
    distance: dict[str, int],
    enclosing: set[str],
) -> list[_Section]:
    """The doc sections that mention any id in `distance` or `enclosing`, best first."""
    ranks = dict.fromkeys(enclosing, 0) | distance
    if not ranks:
        return []
    rows, _, _ = driver.execute_query(
        _MENTIONING, codebase=codebase, ids=list(ranks), routing_=RoutingControl.READ
    )

    def rank(row: dict[str, Any]) -> tuple[int, str, int]:
        ids = [mention[0] for mention in row["mentions"]]
        closest = 0 if resolved_ids.intersection(ids) else 1 + min(ranks[i] for i in ids)
        return closest, row["props"]["path"], row["props"]["start_line"]

    sections: list[_Section] = []
    for row in sorted(rows, key=rank):
        bare: list[str] = []
        spans: set[str] = set()
        for _, label, qualname, path in row["mentions"]:
            names = _names(label, qualname, path)
            bare.extend(names[0])
            spans.update(names[1])
        picks = _named_or_stance(_sentences(row["props"]), bare, spans)
        sections.append(_Section(row["props"], "mention", picks))
    return sections


def _search_sections(driver: Driver, codebase: str, description: str) -> list[_Section]:
    """The best SEARCH_SECTIONS + 1 sections for the description (one more, to tell whether
    the limit cut a guideline), each with the sentences sharing a content word with it."""
    wanted = _content_words(description)
    sections: list[_Section] = []
    for row in search_sections(driver, codebase, description, SEARCH_SECTIONS + 1):
        shared = [
            (sentence, wanted & _content_words(sentence.text))
            for sentence in _sentences(row["props"])
        ]
        best = sorted(
            ((sentence, words) for sentence, words in shared if words),
            key=lambda pair: (
                stance(pair[0].text) == "related",
                -len(pair[1]),
                pair[0].start_line,
            ),
        )
        picks = [(sentence, " ".join(sorted(words))) for sentence, words in best]
        sections.append(_Section(row["props"], "search", picks))
    return sections


def _content_words(text: str) -> set[str]:
    return {
        word
        for word in (match.lower() for match in _WORD.findall(text))
        if len(word) >= 4 and not word.isdigit() and word not in _STOPWORDS
    }


def _merge(sections: list[_Section]) -> tuple[list[Guideline], bool]:
    """(guidelines in section order, each section's in line order; whether PER_SECTION cut
    any). A sentence already cited is skipped, so mentions, which come first, win."""
    seen: set[tuple[str, int, str]] = set()
    per_section: Counter[str] = Counter()
    guidelines: list[Guideline] = []
    cut = False
    for section in sections:
        accepted: list[tuple[Sentence, str]] = []
        for sentence, term in section.picks:
            key = (section.props["path"], sentence.start_line, sentence.text)
            if key in seen:
                continue
            if per_section[section.props["id"]] >= PER_SECTION:
                cut = True
                continue
            seen.add(key)
            per_section[section.props["id"]] += 1
            accepted.append((sentence, term))
        guidelines.extend(
            _guideline(section.props, sentence, term, section.matched_on)
            for sentence, term in sorted(accepted, key=lambda pair: pair[0].start_line)
        )
    return guidelines, cut


def _names(label: str, qualname: str, path: str) -> tuple[list[str], set[str]]:
    """(names a sentence may use bare, names it may use only in a code span) for a symbol.

    A class or function: its qualname bare; its last dotted segments (`Class.method`,
    `method`) only in a code span, so a short name used as an English word does not count.
    A module: its qualname or file path; a package also its directory, with or without the
    trailing slash."""
    if label != "Module":
        parts = qualname.split(".")
        return [qualname], {".".join(parts[start:]) for start in range(len(parts))}
    names = [qualname, path]
    if path.endswith("/__init__.py"):
        directory = path.removesuffix("__init__.py")
        names.extend([directory, directory.rstrip("/")])
    return names, set()


def _sentences(props: dict[str, Any]) -> list[Sentence]:
    return section_sentences(props["text"], props["end_line"])


def _named_or_stance(
    found: list[Sentence], bare: list[str], spans: set[str]
) -> list[tuple[Sentence, str]]:
    """The sentences naming a symbol, or if none does, those with a stance; with a stance
    first, then in line order."""
    named = [(sentence, name) for sentence in found if (name := _named(sentence, bare, spans))]
    pool = named or [
        (sentence, modal_word(sentence.text))
        for sentence in found
        if stance(sentence.text) != "related"
    ]
    return sorted(pool, key=lambda pair: (stance(pair[0].text) == "related", pair[0].start_line))


def _named(sentence: Sentence, bare: list[str], spans: set[str]) -> str:
    """The first name the sentence uses, or "". A bare name must stand alone: not part of a
    longer word, dotted name or path."""
    for name in bare:
        if re.search(rf"(?<![\w./]){re.escape(name)}(?!\w)(?![./]\w)", sentence.text):
            return name
    for match in _SPAN.finditer(sentence.text):
        name = match.group(1).strip().removesuffix("()")
        if name in spans:
            return name
    return ""


def _guideline(props: dict[str, Any], sentence: Sentence, term: str, matched_on: str) -> Guideline:
    return Guideline(
        stance=stance(sentence.text),
        quote=snippet(sentence.text, term),
        citation=Citation(
            path=props["path"],
            heading_path=props["heading_path"],
            start_line=sentence.start_line,
            end_line=sentence.end_line,
        ),
        matched_on=matched_on,  # type: ignore[arg-type]
    )
