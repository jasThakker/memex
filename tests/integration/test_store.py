"""The Neo4j store: schema, full re-index per codebase, round-trip (DESIGN.md section 7).

Needs Docker. Run with `uv run pytest -m neo4j`.
"""

from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
from neo4j import Driver
from neo4j.exceptions import ConstraintError

from memex.config import load_config
from memex.graph.model import ClassNode, DocNode, Edge, GraphBatch, ModuleNode
from memex.graph.store import ensure_schema, label_of, replace_codebase
from memex.ingest.code import index_code

pytestmark = pytest.mark.neo4j

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGISTRY = load_config(FIXTURES / "memex.toml")
LAYERED = index_code(REGISTRY.get("layered_app"))
PLAIN = index_code(REGISTRY.get("plainrepo"))


def stored_counts(driver: Driver, codebase: str) -> tuple[Counter[str], Counter[str]]:
    """(nodes by label, edges by type) stored for one codebase."""
    nodes, _, _ = driver.execute_query(
        "MATCH (n {codebase: $codebase}) RETURN labels(n)[0] AS label, count(*) AS n",
        codebase=codebase,
    )
    edges, _, _ = driver.execute_query(
        "MATCH (a {codebase: $codebase})-[r]->() RETURN type(r) AS kind, count(*) AS n",
        codebase=codebase,
    )
    return (
        Counter({row["label"]: row["n"] for row in nodes}),
        Counter({row["kind"]: row["n"] for row in edges}),
    )


def expected_counts(batch: GraphBatch) -> tuple[Counter[str], Counter[str]]:
    return Counter(label_of(node) for node in batch.nodes), Counter(e.kind for e in batch.edges)


def test_round_trip_keeps_every_node_and_edge(driver: Driver) -> None:
    ensure_schema(driver)
    replace_codebase(driver, LAYERED)

    assert stored_counts(driver, "layered_app") == expected_counts(LAYERED)


def test_node_and_edge_properties_are_stored_as_in_the_model(driver: Driver) -> None:
    ensure_schema(driver)
    replace_codebase(driver, LAYERED)

    order = next(n for n in LAYERED.nodes if isinstance(n, ClassNode) and n.name == "Order")
    rows, _, _ = driver.execute_query(
        "MATCH (n:Class {id: $id}) RETURN properties(n) AS props", id=order.id
    )
    assert rows[0]["props"] == {
        "id": order.id,
        "codebase": "layered_app",
        "name": "Order",
        "qualname": "app.db.models.orders.Order",
        "path": "app/db/models/orders.py",
        "line": order.line,
        "end_line": order.end_line,
        "layer": "db_models",
        "domain": "order",
        "tablename": "orders",
    }  # no docstring: None is not written

    rows, _, _ = driver.execute_query(
        "MATCH (:Class {id: $id})-[r:REFERENCES {attr: 'user_id'}]->(t:Class) "
        "RETURN properties(r) AS props, t.name AS target",
        id=order.id,
    )
    assert rows[0]["target"] == "User"
    assert rows[0]["props"] == {
        "kind": "foreign_key",
        "attr": "user_id",
        "line": 14,
        "extractor": "sqlalchemy",
    }

    rows, _, _ = driver.execute_query(
        "MATCH (c:Codebase {id: 'layered_app'}) RETURN properties(c) AS props"
    )
    props = rows[0]["props"]
    assert props["extractors"] == ["sqlalchemy"]
    assert (props["files"], props["unresolved_calls"], props["parse_errors"]) == (27, 3, 0)

    rows, _, _ = driver.execute_query(
        "MATCH (:Function)-[r:CALLS]->(f:Function {name: 'get_name'}) RETURN r.confidence AS c"
    )
    assert [row["c"] for row in rows] == ["inferred"]


def test_reindex_replaces_only_its_own_codebase(driver: Driver) -> None:
    ensure_schema(driver)
    replace_codebase(driver, LAYERED)
    replace_codebase(driver, PLAIN)

    # Re-index layered_app with one module (and everything touching it) gone.
    gone = {
        n.id
        for n in LAYERED.nodes
        if isinstance(n, ModuleNode | ClassNode) and n.path == "app/db/models/orders.py"
    }
    smaller = replace(
        LAYERED,
        nodes=tuple(n for n in LAYERED.nodes if n.id not in gone),
        edges=tuple(e for e in LAYERED.edges if not {e.source, e.target} & gone),
    )
    replace_codebase(driver, smaller)

    assert stored_counts(driver, "layered_app") == expected_counts(smaller)
    assert stored_counts(driver, "plainrepo") == expected_counts(PLAIN)


def test_a_failure_inside_the_transaction_keeps_the_previous_graph(driver: Driver) -> None:
    # The first write stores layered_app without the orders model. Then a node of another
    # codebase takes the id that model has, so the full re-index fails on the uniqueness
    # constraint after it has already deleted the old nodes: the delete must roll back.
    ensure_schema(driver)
    orders = {
        n.id
        for n in LAYERED.nodes
        if isinstance(n, ModuleNode | ClassNode) and n.path == "app/db/models/orders.py"
    }
    smaller = replace(
        LAYERED,
        nodes=tuple(n for n in LAYERED.nodes if n.id not in orders),
        edges=tuple(e for e in LAYERED.edges if not {e.source, e.target} & orders),
    )
    replace_codebase(driver, smaller)
    driver.execute_query("CREATE (:Module {id: $id, codebase: 'squatter'})", id=sorted(orders)[0])

    with pytest.raises(ConstraintError):
        replace_codebase(driver, LAYERED)

    assert stored_counts(driver, "layered_app") == expected_counts(smaller)


def test_a_rejected_batch_leaves_the_previous_graph_intact(driver: Driver) -> None:
    ensure_schema(driver)
    replace_codebase(driver, LAYERED)
    broken = replace(
        LAYERED,
        edges=(*LAYERED.edges, Edge(kind="CALLS", source="layered_app:nope", target="x")),
    )

    with pytest.raises(ValueError, match="dangling"):
        replace_codebase(driver, broken)

    assert stored_counts(driver, "layered_app") == expected_counts(LAYERED)


def test_doc_nodes_and_mentions_round_trip(driver: Driver) -> None:
    ensure_schema(driver)
    doc = DocNode(
        id="layered_app:doc:docs/db.md#models",
        codebase="layered_app",
        path="docs/db.md",
        heading_path="Database > Models",
        anchor="models",
        text="Orders reference `User` through user_id.",
        start_line=3,
        end_line=8,
        kind="contributor",
    )
    user = next(n for n in LAYERED.nodes if isinstance(n, ClassNode) and n.name == "User")
    mention = Edge(kind="MENTIONS", source=doc.id, target=user.id, match="backtick_name")
    replace_codebase(
        driver, replace(LAYERED, nodes=(*LAYERED.nodes, doc), edges=(*LAYERED.edges, mention))
    )

    rows, _, _ = driver.execute_query(
        "CALL db.index.fulltext.queryNodes('doc_text', 'user_id') YIELD node "
        "MATCH (node)-[m:MENTIONS]->(c:Class) RETURN node.kind AS kind, m.match AS match, "
        "c.name AS target"
    )
    assert [dict(row) for row in rows] == [
        {"kind": "contributor", "match": "backtick_name", "target": "User"}
    ]


def test_schema_has_constraints_and_indexes_and_is_idempotent(driver: Driver) -> None:
    ensure_schema(driver)
    ensure_schema(driver)

    constraints, _, _ = driver.execute_query(
        "SHOW CONSTRAINTS YIELD type, labelsOrTypes, properties "
        "WHERE type = 'UNIQUENESS' RETURN labelsOrTypes[0] AS label, properties AS props"
    )
    assert {(row["label"], tuple(row["props"])) for row in constraints} == {
        (label, ("id",)) for label in ("Codebase", "Module", "Class", "Function", "External", "Doc")
    }

    indexes, _, _ = driver.execute_query(
        "SHOW INDEXES YIELD name, type, labelsOrTypes, properties, owningConstraint "
        "WHERE owningConstraint IS NULL AND type IN ['RANGE', 'FULLTEXT'] "
        "RETURN type, labelsOrTypes[0] AS label, properties AS props, name"
    )
    assert {(row["type"], row["label"], tuple(row["props"])) for row in indexes} == {
        ("RANGE", "Class", ("codebase", "name")),
        ("RANGE", "Function", ("codebase", "name")),
        ("RANGE", "External", ("codebase", "name")),
        ("RANGE", "Module", ("codebase", "qualname")),
        ("FULLTEXT", "Doc", ("heading_path", "text")),
    }
    assert "doc_text" in {row["name"] for row in indexes}
