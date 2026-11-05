"""check_change (DESIGN.md section 10, ADR-002): which code a proposed change affects and
which documented rules apply. No LLM: the calling agent makes the final judgment.

- Symbols: the proposal's explicit `symbols`, or else the code-shaped names in its
  description (`rules.code_tokens`); at most MAX_TOKENS of them. Each goes through the symbol
  rule: one match is resolved, several are listed as ambiguous with at most MAX_CANDIDATES
  candidates (never guessed), none is unresolved.
- Affected: one impact walk from the start sets of all resolved symbols, AFFECTED_DEPTH
  edges deep, counted by layer (None last).
- `truncated` is set when names or candidates were cut.
"""

from collections import Counter

from neo4j import Driver

from memex.graph.model import code_id
from memex.query.docs import MAX_QUERY_CHARS
from memex.query.impact import start_set, walk
from memex.query.models import (
    AmbiguousName,
    ChangeCheck,
    ChangeProposal,
    ImpactSummary,
    LayerCount,
    SymbolRef,
)
from memex.query.rules import code_tokens
from memex.query.symbols import resolve_symbol

MAX_TOKENS = 10
MAX_CANDIDATES = 5
AFFECTED_DEPTH = 3


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

    return ChangeCheck(
        codebase=codebase,
        resolved_symbols=list(resolved.values()),
        ambiguous=ambiguous,
        unresolved=unresolved,
        affected=_affected(driver, codebase, list(resolved)),
        guidelines=[],
        truncated=truncated,
    )


def _affected(driver: Driver, codebase: str, qualnames: list[str]) -> ImpactSummary:
    """Dependents of all `qualnames` together, counted by layer, None last."""
    start_ids = [i for q in qualnames for i in start_set(driver, code_id(codebase, q))]
    if not start_ids:
        return ImpactSummary(total=0, layers=[])
    _, found = walk(driver, list(dict.fromkeys(start_ids)), AFFECTED_DEPTH)
    counts = Counter(dependent.symbol.layer for dependent in found)
    order = sorted(counts, key=lambda layer: (layer is None, layer or ""))
    return ImpactSummary(
        total=len(found), layers=[LayerCount(layer=layer, count=counts[layer]) for layer in order]
    )
