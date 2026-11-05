"""callers and callees (DESIGN.md section 10): the CALLS graph around one symbol.

Breadth first, one query per depth level. Each function appears once, at its shortest
distance; ties between two functions it could be reached through go to the first by qualname.
A recursive function is listed as its own caller and callee, at distance 1.
A class stands for its own `__init__` (constructor calls point there); a class that inherits
its `__init__`, and a module, have no calls.
"""

from typing import Literal

from neo4j import Driver, RoutingControl

from memex.graph.model import code_id
from memex.query.models import CallGraph, CallHop, SymbolRef
from memex.query.symbols import check_limit, resolve_symbol, symbol_ref

MAX_DEPTH = 5
Direction = Literal["callers", "callees"]

# One step from the frontier: `f` is the function reached, `s` the frontier function it is
# reached through.
_STEP = {
    "callers": "MATCH (f:Function)-[r:CALLS]->(s:Function) WHERE s.id IN $ids ",
    "callees": "MATCH (s:Function)-[r:CALLS]->(f:Function) WHERE s.id IN $ids ",
}
_RETURN = (
    "RETURN s.qualname AS via, r.line AS line, r.confidence AS confidence, "
    "labels(f)[0] AS label, properties(f) AS props "
    "ORDER BY props.qualname, via"
)


def callers(
    driver: Driver, codebase: str, symbol: str, depth: int = 1, limit: int = 12
) -> CallGraph:
    """Functions that call `symbol`, up to `depth` calls away."""
    return _walk(driver, codebase, symbol, "callers", depth, limit)


def callees(
    driver: Driver, codebase: str, symbol: str, depth: int = 1, limit: int = 12
) -> CallGraph:
    """Functions that `symbol` calls, up to `depth` calls away."""
    return _walk(driver, codebase, symbol, "callees", depth, limit)


def check_depth(depth: int, name: str = "depth") -> None:
    if not 1 <= depth <= MAX_DEPTH:
        raise ValueError(f"{name} must be between 1 and {MAX_DEPTH}, got {depth}")


def _walk(
    driver: Driver, codebase: str, symbol: str, direction: Direction, depth: int, limit: int
) -> CallGraph:
    check_depth(depth)
    check_limit(limit)
    ref, candidates, truncated = resolve_symbol(driver, codebase, symbol, limit)
    graph = CallGraph(
        codebase=codebase,
        symbol=ref,
        candidates=candidates,
        direction=direction,
        depth=depth,
        truncated=truncated,
    )
    start = _start_function(driver, codebase, ref) if ref else None
    if start is None:
        return graph

    seen = {start}
    frontier = [start]
    found: list[CallHop] = []
    for distance in range(1, depth + 1):
        rows, _, _ = driver.execute_query(
            _STEP[direction] + _RETURN,
            ids=[code_id(codebase, qualname) for qualname in frontier],
            routing_=RoutingControl.READ,
        )
        frontier = []
        for row in rows:
            function = symbol_ref(row["label"], row["props"])
            recursion = distance == 1 and function.qualname == start
            if function.qualname in seen and not recursion:
                continue
            if not recursion:
                seen.add(function.qualname)
                frontier.append(function.qualname)
            found.append(
                CallHop(
                    function=function,
                    via=row["via"],
                    line=row["line"],
                    confidence=row["confidence"],
                    distance=distance,
                )
            )
        if not frontier or len(found) > limit:
            break
    return graph.model_copy(update={"calls": found[:limit], "truncated": len(found) > limit})


def _start_function(driver: Driver, codebase: str, ref: SymbolRef) -> str | None:
    """The qualname of the function to walk from, or None if `ref` has no calls."""
    if ref.kind == "function":
        return ref.qualname
    if ref.kind == "module":
        return None
    rows, _, _ = driver.execute_query(
        "MATCH (:Class {id: $id})-[:DEFINES]->(f:Function {name: '__init__'}) "
        "RETURN f.qualname AS qualname",
        id=code_id(codebase, ref.qualname),
        routing_=RoutingControl.READ,
    )
    return rows[0]["qualname"] if rows else None
