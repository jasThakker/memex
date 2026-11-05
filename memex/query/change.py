"""check_change (DESIGN.md section 10, ADR-002): which code a proposed change affects and
which documented rules apply. No LLM: the calling agent makes the final judgment.

- Symbols: the proposal's explicit `symbols`, or else the code-shaped names in its
  description (`rules.code_tokens`); at most MAX_TOKENS of them. Each goes through the symbol
  rule: one match is resolved, several are listed as ambiguous with at most MAX_CANDIDATES
  candidates (never guessed), none is unresolved.
- Affected: one impact walk from the start sets of all resolved symbols, AFFECTED_DEPTH
  edges deep, counted by layer (None last).
- Guidelines from doc sections that MENTION any symbol in that walk (the resolved symbols,
  their members and their dependents), ranked as impact_of ranks docs: those on a resolved
  symbol first, then on a member, then by the closest dependent, then by path and line. In
  each section, the sentences naming a mentioned symbol, or if none does (the mention is in
  the heading) those with a stance; at most PER_SECTION, those with a stance first. Each
  guideline quotes one sentence and cites its own lines.
- Then guidelines from a full-text search on the description: the best SEARCH_SECTIONS
  sections, and in each the sentences sharing a content word with the description (four
  letters or more, not a common English word), those with a stance first, then those
  sharing more words; at most PER_SECTION. A sentence found both ways is listed once, as a
  mention.
- At most MAX_GUIDELINES guidelines.
- `truncated` is set when names, candidates or guidelines were cut.
"""

import re
from collections import Counter
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
from memex.query.rules import Sentence, code_tokens, sentences, stance
from memex.query.symbols import resolve_symbol

MAX_TOKENS = 10
MAX_CANDIDATES = 5
AFFECTED_DEPTH = 3
MAX_GUIDELINES = 6
PER_SECTION = 2
SEARCH_SECTIONS = 5

_WORD = re.compile(r"\w+")
# Common words a description and a rule share without being about the same thing.
_STOPWORDS = frozenset(
    [
        "about",
        "after",
        "also",
        "always",
        "avoid",
        "been",
        "before",
        "could",
        "does",
        "each",
        "from",
        "have",
        "into",
        "just",
        "like",
        "more",
        "must",
        "need",
        "never",
        "only",
        "other",
        "prefer",
        "should",
        "some",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "want",
        "were",
        "what",
        "when",
        "where",
        "which",
        "will",
        "with",
        "would",
        "your",
    ]
)

_MENTIONING = (
    "MATCH (doc:Doc {codebase: $codebase})-[:MENTIONS]->(c) WHERE c.id IN $ids "
    "WITH DISTINCT doc "
    "MATCH (doc)-[:MENTIONS]->(m) WHERE m.id IN $ids "
    "RETURN properties(doc) AS props, "
    "collect([m.id, labels(m)[0], m.qualname, m.path]) AS mentions"
)


def check_change(driver: Driver, codebase: str, proposal: ChangeProposal) -> ChangeCheck:
    """The symbols a proposal names, what depends on them, and the rules that apply."""
    description = proposal.description.strip()
    if not description:
        raise ValueError("description must not be empty")
    if len(description) > MAX_QUERY_CHARS:
        raise ValueError(
            f"description must be at most {MAX_QUERY_CHARS} characters, got {len(description)}"
        )
    names = list(dict.fromkeys(proposal.symbols)) or code_tokens(description)
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
    guidelines = _merge(
        _mention_guidelines(driver, codebase, resolved_ids, distance)
        + _search_guidelines(driver, codebase, description)
    )

    return ChangeCheck(
        codebase=codebase,
        resolved_symbols=list(resolved.values()),
        ambiguous=ambiguous,
        unresolved=unresolved,
        affected=_summary(found),
        guidelines=guidelines[:MAX_GUIDELINES],
        truncated=truncated or len(guidelines) > MAX_GUIDELINES,
    )


def _summary(found: list[Any]) -> ImpactSummary:
    """Dependents counted by layer, None last."""
    counts = Counter(dependent.symbol.layer for dependent in found)
    order = sorted(counts, key=lambda layer: (layer is None, layer or ""))
    return ImpactSummary(
        total=len(found), layers=[LayerCount(layer=layer, count=counts[layer]) for layer in order]
    )


def _mention_guidelines(
    driver: Driver, codebase: str, resolved_ids: set[str], distance: dict[str, int]
) -> list[Guideline]:
    """Cited sentences from the doc sections that mention any id in `distance`, best first."""
    if not distance:
        return []
    rows, _, _ = driver.execute_query(
        _MENTIONING, codebase=codebase, ids=list(distance), routing_=RoutingControl.READ
    )

    def rank(row: dict[str, Any]) -> tuple[int, str, int]:
        ids = [mention[0] for mention in row["mentions"]]
        closest = 0 if resolved_ids.intersection(ids) else 1 + min(distance[i] for i in ids)
        return closest, row["props"]["path"], row["props"]["start_line"]

    guidelines: list[Guideline] = []
    for row in sorted(rows, key=rank):
        names = [name for mention in row["mentions"] for name in _names(*mention[1:])]
        for sentence, name in _pick(_body_sentences(row["props"]), names):
            guidelines.append(_guideline(row["props"], sentence, name, "mention"))
    return guidelines


def _search_guidelines(driver: Driver, codebase: str, description: str) -> list[Guideline]:
    """Cited sentences from the sections a full-text search on the description finds."""
    wanted = _content_words(description)
    guidelines: list[Guideline] = []
    for row in search_sections(driver, codebase, description, SEARCH_SECTIONS):
        shared = [
            (sentence, wanted & _content_words(sentence.text))
            for sentence in _body_sentences(row["props"])
        ]
        best = sorted(
            ((sentence, words) for sentence, words in shared if words),
            key=lambda pair: (
                stance(pair[0].text) == "related",
                -len(pair[1]),
                pair[0].start_line,
            ),
        )[:PER_SECTION]
        for sentence, words in sorted(best, key=lambda pair: pair[0].start_line):
            term = " ".join(sorted(words))
            guidelines.append(_guideline(row["props"], sentence, term, "search"))
    return guidelines


def _content_words(text: str) -> set[str]:
    return {
        word
        for word in (match.lower() for match in _WORD.findall(text))
        if len(word) >= 4 and word not in _STOPWORDS
    }


def _merge(guidelines: list[Guideline]) -> list[Guideline]:
    """Each cited sentence once, the first occurrence kept (mentions come first)."""
    seen: set[tuple[str, int]] = set()
    merged: list[Guideline] = []
    for guideline in guidelines:
        key = (guideline.citation.path, guideline.citation.start_line)
        if key not in seen:
            seen.add(key)
            merged.append(guideline)
    return merged


def _names(label: str, qualname: str, path: str) -> list[str]:
    """How a doc sentence may name a symbol: a class or function by qualname or short name, a
    module by qualname or path (a package also by its directory, `pkg/sub/`)."""
    if label != "Module":
        return [qualname, qualname.rsplit(".", 1)[-1]]
    names = [qualname, path]
    if path.endswith("/__init__.py"):
        names.append(path.removesuffix("__init__.py"))
    return names


def _body_sentences(props: dict[str, Any]) -> list[Sentence]:
    """The sentences of a section body. `text` is trimmed of outer blank lines and ends on
    `end_line`, so its first line is `end_line` minus its line breaks."""
    text = props["text"]
    if not text:
        return []
    return sentences(text, first_line=props["end_line"] - text.count("\n"))


def _pick(found: list[Sentence], names: list[str]) -> list[tuple[Sentence, str]]:
    """At most PER_SECTION (sentence, matched name) pairs, in line order: the sentences naming
    one of `names`, or if none does, those with a stance. Sentences with a stance first."""
    named = [(sentence, name) for sentence in found if (name := _named(sentence, names))]
    pool = named or [(sentence, "") for sentence in found if stance(sentence.text) != "related"]
    best = sorted(pool, key=lambda pair: (stance(pair[0].text) == "related", pair[0].start_line))
    return sorted(best[:PER_SECTION], key=lambda pair: pair[0].start_line)


def _named(sentence: Sentence, names: list[str]) -> str:
    """The first of `names` the sentence contains as a whole name, or ""."""
    for name in names:
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", sentence.text):
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
