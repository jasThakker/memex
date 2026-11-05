"""Symbol lookup (DESIGN.md section 10): the symbol rule every `symbol` argument goes through,
and the find_symbol tool.

A symbol is given as a full qualname, or as its last dotted segments (`get_one`,
`UserRepository.get_one`). Segments match whole: `Repository` does not match `UserRepository`.
"""

from typing import Any, Literal

from neo4j import Driver, RoutingControl

from memex.query.models import Symbol, SymbolKind, SymbolRef, SymbolSearch

MAX_LIMIT = 200
KINDS: dict[str, SymbolKind] = {"Module": "module", "Class": "class", "Function": "function"}
_LABELS = {kind: label for label, kind in KINDS.items()}

# The node and its label, for any Module, Class or Function in one codebase.
_SYMBOL_NODES = (
    "MATCH (n {codebase: $codebase}) "
    "WHERE (n:Module OR n:Class OR n:Function) AND ($labels IS NULL OR labels(n)[0] IN $labels) "
)
_RETURN = "RETURN labels(n)[0] AS label, properties(n) AS props"
# find_symbol's match tiers: 0 exact qualname, 1 qualname suffix, 2 last segment contains it.
_RANKED = (
    "WITH n, CASE "
    "WHEN n.qualname = $query THEN 0 "
    "WHEN n.qualname ENDS WITH $suffix THEN 1 "
    "WHEN toLower(last(split(n.qualname, '.'))) CONTAINS toLower($query) THEN 2 "
    "END AS rank "
    "WHERE rank IS NOT NULL "
)


def resolve_symbol(
    driver: Driver, codebase: str, symbol: str, limit: int = MAX_LIMIT
) -> tuple[SymbolRef | None, list[SymbolRef], bool]:
    """(symbol, candidates, truncated): (the symbol, [], False) for one match, (None,
    candidates, truncated) for several, (None, [], False) for none.

    An exact qualname wins over symbols whose qualname only ends with it. Candidates are
    ordered by qualname, at most `limit` of them; `truncated` says more matched.
    """
    symbol = symbol.strip()
    if not symbol:
        raise ValueError("symbol must not be empty")
    check_limit(limit)
    rows, _, _ = driver.execute_query(
        _SYMBOL_NODES
        + "AND (n.qualname = $symbol OR n.qualname ENDS WITH $suffix) "
        + _RETURN
        + " ORDER BY props.qualname = $symbol DESC, props.qualname LIMIT $fetch",
        codebase=codebase,
        symbol=symbol,
        suffix=f".{symbol}",
        labels=None,
        fetch=limit + 1,
        routing_=RoutingControl.READ,
    )
    refs = [symbol_ref(row["label"], row["props"]) for row in rows]
    if refs and refs[0].qualname == symbol:
        return refs[0], [], False
    if len(refs) == 1:
        return refs[0], [], False
    return None, refs[:limit], len(refs) > limit


def find_symbol(
    driver: Driver,
    codebase: str,
    name: str,
    kind: Literal["module", "class", "function", "any"] = "any",
    limit: int = 10,
) -> SymbolSearch:
    """Symbols matching `name`, best first: the exact qualname, then symbols whose qualname
    ends with `name`, then symbols whose last segment contains `name` ignoring case. Ties are
    ordered by qualname."""
    query = name.strip()
    if not query:
        raise ValueError("name must not be empty")
    if kind != "any" and kind not in _LABELS:
        raise ValueError(f"kind must be module, class, function or any, got {kind!r}")
    check_limit(limit)
    rows, _, _ = driver.execute_query(
        _SYMBOL_NODES + _RANKED + _RETURN + " ORDER BY rank, props.qualname LIMIT $fetch",
        codebase=codebase,
        query=query,
        suffix=f".{query}",
        labels=None if kind == "any" else [_LABELS[kind]],
        fetch=limit + 1,
        routing_=RoutingControl.READ,
    )
    symbols = [full_symbol(row["label"], row["props"]) for row in rows]
    return SymbolSearch(
        codebase=codebase,
        query=name,
        kind=kind,
        symbols=symbols[:limit],
        truncated=len(symbols) > limit,
    )


def check_limit(limit: int, name: str = "limit") -> None:
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"{name} must be between 1 and {MAX_LIMIT}, got {limit}")


def symbol_ref(label: str, props: dict[str, Any]) -> SymbolRef:
    """A SymbolRef from a stored Module, Class or Function node."""
    return SymbolRef(
        qualname=props["qualname"],
        kind=KINDS[label],
        path=props["path"],
        line=props.get("line"),
        layer=props.get("layer"),
        domain=props.get("domain"),
    )


def full_symbol(label: str, props: dict[str, Any]) -> Symbol:
    return Symbol(
        **symbol_ref(label, props).model_dump(),
        signature=props.get("signature"),
        docstring=props.get("docstring"),
    )
