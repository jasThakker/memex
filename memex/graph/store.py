"""Neo4j writes: the schema, and a full re-index of one codebase (DESIGN.md section 7).

- One uniqueness constraint on `id` per label; indexes on (codebase, name) for Class, Function
  and External and on (codebase, qualname) for Module; the full-text index `doc_text` on
  Doc(heading_path, text).
- `replace_codebase` validates the batch first, then deletes every node of that codebase and
  writes the batch with UNWIND, in one transaction: a failed re-index keeps the old graph.
- Properties set to None are not written (Neo4j has no null properties); tuples become lists.
  The edge field `ref_kind` is stored as `kind`.
All read queries live in memex.query.
"""

import os
from collections import Counter, defaultdict
from dataclasses import asdict, fields
from typing import Any, get_args

from neo4j import Driver, GraphDatabase, ManagedTransaction

from memex.graph.model import (
    ClassNode,
    CodebaseNode,
    DocNode,
    Edge,
    EdgeKind,
    ExternalNode,
    FunctionNode,
    GraphBatch,
    ModuleNode,
    Node,
)

BATCH_SIZE = 1000  # rows per UNWIND
LABELS: dict[type, str] = {
    CodebaseNode: "Codebase",
    ModuleNode: "Module",
    ClassNode: "Class",
    FunctionNode: "Function",
    ExternalNode: "External",
    DocNode: "Doc",
}
EDGE_KINDS = frozenset(get_args(EdgeKind))
_EDGE_ENDPOINTS = frozenset({"kind", "source", "target"})


def connect() -> Driver:
    """A driver for the dev database: NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD, with the
    defaults of docker-compose.yml."""
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "memex-dev-password")
    return GraphDatabase.driver(uri, auth=(user, password))


def ensure_schema(driver: Driver) -> None:
    """Create the constraints and indexes if they are missing. Safe to run every time."""
    statements = [
        f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
        for label in LABELS.values()
    ]
    statements += [
        f"CREATE INDEX {label.lower()}_codebase_name IF NOT EXISTS "
        f"FOR (n:{label}) ON (n.codebase, n.name)"
        for label in ("Class", "Function", "External")
    ]
    statements += [
        "CREATE INDEX module_codebase_qualname IF NOT EXISTS "
        "FOR (n:Module) ON (n.codebase, n.qualname)",
        "CREATE FULLTEXT INDEX doc_text IF NOT EXISTS FOR (n:Doc) ON EACH [n.heading_path, n.text]",
    ]
    for statement in statements:
        driver.execute_query(statement)
    driver.execute_query("CALL db.awaitIndexes()")


def replace_codebase(driver: Driver, batch: GraphBatch) -> None:
    """Replace everything stored for `batch.codebase` with the batch, atomically."""
    validate(batch)
    with driver.session() as session:
        session.execute_write(_replace, batch)


def validate(batch: GraphBatch) -> None:
    """Raise ValueError for a batch the store must not write."""
    counts = Counter(node.id for node in batch.nodes)
    duplicates = sorted(node_id for node_id, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate node ids: {duplicates[:5]}")
    foreign = sorted(node.id for node in batch.nodes if node.codebase != batch.codebase)
    if foreign:
        raise ValueError(f"nodes from another codebase than {batch.codebase!r}: {foreign[:5]}")
    unknown = sorted({edge.kind for edge in batch.edges} - EDGE_KINDS)
    if unknown:
        raise ValueError(f"unknown edge kinds: {unknown}")
    dangling = [
        (edge.kind, edge.source, edge.target)
        for edge in batch.edges
        if edge.source not in counts or edge.target not in counts
    ]
    if dangling:
        raise ValueError(f"{len(dangling)} dangling edges, for example {dangling[0]}")


def label_of(node: Node) -> str:
    return LABELS[type(node)]


def node_properties(node: Node) -> dict[str, Any]:
    return {key: _value(value) for key, value in asdict(node).items() if value is not None}


def edge_properties(edge: Edge) -> dict[str, Any]:
    """The properties an edge's kind uses: set fields other than kind, source and target."""
    properties: dict[str, Any] = {}
    for field in fields(edge):
        value = getattr(edge, field.name)
        if field.name in _EDGE_ENDPOINTS or value is None or value == ():
            continue
        properties["kind" if field.name == "ref_kind" else field.name] = _value(value)
    return properties


def _value(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value


def _replace(tx: ManagedTransaction, batch: GraphBatch) -> None:
    for label in LABELS.values():
        tx.run(
            f"MATCH (n:{label} {{codebase: $codebase}}) DETACH DELETE n", codebase=batch.codebase
        )

    nodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in batch.nodes:
        nodes[label_of(node)].append(node_properties(node))
    for label, rows in nodes.items():
        for chunk in _chunks(rows):
            tx.run(f"UNWIND $rows AS row CREATE (n:{label}) SET n = row", rows=chunk)

    labels = {node.id: label_of(node) for node in batch.nodes}
    edges: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for edge in batch.edges:
        key = (edge.kind, labels[edge.source], labels[edge.target])
        edges[key].append(
            {"source": edge.source, "target": edge.target, "props": edge_properties(edge)}
        )
    for (kind, source_label, target_label), rows in edges.items():
        for chunk in _chunks(rows):
            tx.run(
                f"UNWIND $rows AS row "
                f"MATCH (a:{source_label} {{id: row.source}}) "
                f"MATCH (b:{target_label} {{id: row.target}}) "
                f"CREATE (a)-[r:{kind}]->(b) SET r = row.props",
                rows=chunk,
            )


def _chunks(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [rows[start : start + BATCH_SIZE] for start in range(0, len(rows), BATCH_SIZE)]
