"""impact_of (DESIGN.md section 10): what depends on a symbol.

- The start set is the symbol plus everything it defines, transitively, so the impact of a
  class includes code that calls its methods.
- Dependents are found by walking CALLS, INHERITS, REFERENCES, IMPORTS and USES edges
  backwards, breadth first, up to `max_depth`. Each appears once, at its shortest distance, with its
  edge path back to the start set; ties go to the first target by qualname.
- Modules are leaves: a module that imports a dependent is listed, but what imports that
  module is not followed (otherwise most of a codebase depends on anything by depth 3).
- A class reached by REFERENCES is a leaf too: a model with a relationship to the start set
  is listed, but what depends on that model does not depend on the start set through it.
- The closest `limit` dependents are kept, grouped by layer (None last); `total` counts all.
- Up to MAX_DOCS doc sections that mention the symbol or a dependent are listed: those on the
  symbol itself first, then those on its members, then by the distance of the closest
  dependent they mention, then by path. Each lists only the mentions in the impact set.
- `truncated` is set when dependents or docs (or candidates) were cut.
"""

from collections import defaultdict
from typing import Any

from neo4j import Driver, RoutingControl

from memex.graph.model import code_id
from memex.query.calls import check_depth
from memex.query.models import Dependent, DocRef, Impact, LayerGroup, PathStep
from memex.query.symbols import check_limit, resolve_symbol, symbol_ref

IMPACT_EDGES = ["CALLS", "INHERITS", "REFERENCES", "IMPORTS", "USES"]
# A class that only references a dependent does not pass the dependency on to its own
# dependents, so the walk stops there.
LEAF_EDGES = {"REFERENCES"}
MAX_DOCS = 5

_START_SET = "MATCH (:Module|Class|Function {id: $id})-[:DEFINES*0..]->(n) RETURN n.id AS id"
_STEP = (
    "MATCH (t:Module|Class|Function) WHERE t.id IN $ids "
    "MATCH (d)-[r]->(t) WHERE type(r) IN $edges AND (d:Module OR d:Class OR d:Function) "
    "RETURN d.id AS id, labels(d)[0] AS label, properties(d) AS props, "
    "type(r) AS edge, t.id AS target, t.qualname AS to "
    "ORDER BY props.qualname, to, edge"
)
_DOCS = (
    "MATCH (doc:Doc {codebase: $codebase})-[:MENTIONS]->(c) WHERE c.id IN $ids "
    "WITH DISTINCT doc "
    "MATCH (doc)-[:MENTIONS]->(m) "
    "RETURN properties(doc) AS props, collect([m.id, m.qualname]) AS mentions"
)


def impact_of(
    driver: Driver, codebase: str, symbol: str, max_depth: int = 3, limit: int = 8
) -> Impact:
    """Code that depends on `symbol`, up to `max_depth` edges away, and the docs about it."""
    check_depth(max_depth, "max_depth")
    check_limit(limit)
    ref, candidates, truncated = resolve_symbol(driver, codebase, symbol, limit)
    impact = Impact(
        codebase=codebase,
        symbol=ref,
        candidates=candidates,
        max_depth=max_depth,
        truncated=truncated,
    )
    if ref is None:
        return impact

    symbol_id = code_id(codebase, ref.qualname)
    distance, found = walk(driver, start_set(driver, symbol_id), max_depth)
    docs, docs_cut = _docs(driver, codebase, symbol_id, distance)
    return impact.model_copy(
        update={
            "total": len(found),
            "layers": _by_layer(found[:limit]),
            "docs": docs,
            "truncated": truncated or len(found) > limit or docs_cut,
        }
    )


def start_set(driver: Driver, node_id: str) -> list[str]:
    """The ids of a Module, Class or Function and of everything it DEFINES, transitively."""
    rows, _, _ = driver.execute_query(_START_SET, id=node_id, routing_=RoutingControl.READ)
    return [row["id"] for row in rows]


def walk(
    driver: Driver, start_ids: list[str], max_depth: int
) -> tuple[dict[str, int], list[Dependent]]:
    """(distance of every id reached, the start ids at 0; the dependents in the order found)

    Breadth first over IMPACT_EDGES backwards, each node once at its shortest distance, with
    its edge path back to the start set. Modules, and classes reached by REFERENCES, are
    leaves."""
    distance: dict[str, int] = dict.fromkeys(start_ids, 0)
    paths: dict[str, list[PathStep]] = {}
    found: list[Dependent] = []
    frontier = list(distance)
    for step in range(1, max_depth + 1):
        if not frontier:
            break
        rows, _, _ = driver.execute_query(
            _STEP, ids=frontier, edges=IMPACT_EDGES, routing_=RoutingControl.READ
        )
        frontier = []
        for row in rows:
            if row["id"] in distance:
                continue
            distance[row["id"]] = step
            paths[row["id"]] = [PathStep(edge=row["edge"], to=row["to"])] + paths.get(
                row["target"], []
            )
            found.append(
                Dependent(
                    symbol=symbol_ref(row["label"], row["props"]),
                    distance=step,
                    path=paths[row["id"]],
                )
            )
            if row["label"] != "Module" and row["edge"] not in LEAF_EDGES:
                frontier.append(row["id"])
    return distance, found


def _by_layer(dependents: list[Dependent]) -> list[LayerGroup]:
    """Groups by layer name, None last; `dependents` is already in (distance, qualname) order."""
    grouped: dict[str | None, list[Dependent]] = defaultdict(list)
    for dependent in dependents:
        grouped[dependent.symbol.layer].append(dependent)
    order = sorted(grouped, key=lambda layer: (layer is None, layer or ""))
    return [LayerGroup(layer=layer, dependents=grouped[layer]) for layer in order]


def _docs(
    driver: Driver, codebase: str, symbol_id: str, distance: dict[str, int]
) -> tuple[list[DocRef], bool]:
    """(the first MAX_DOCS doc sections mentioning any id in `distance`, whether more did)."""
    rows, _, _ = driver.execute_query(
        _DOCS, codebase=codebase, ids=list(distance), routing_=RoutingControl.READ
    )

    def rank(row: dict[str, Any]) -> tuple[int, str, int]:
        ids = [node_id for node_id, _ in row["mentions"]]
        # 0: the symbol itself, 1: a member of the start set, 1 + d: a dependent at distance d
        closest = 0 if symbol_id in ids else 1 + min(distance[i] for i in ids if i in distance)
        return closest, row["props"]["path"], row["props"]["start_line"]

    ranked = sorted(rows, key=rank)
    docs = [
        DocRef(
            path=row["props"]["path"],
            heading_path=row["props"]["heading_path"],
            start_line=row["props"]["start_line"],
            end_line=row["props"]["end_line"],
            mentions=sorted(q for node_id, q in row["mentions"] if node_id in distance),
        )
        for row in ranked[:MAX_DOCS]
    ]
    return docs, len(ranked) > MAX_DOCS
