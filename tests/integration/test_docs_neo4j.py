"""Docs in Neo4j: Doc nodes and MENTIONS from `index_codebase` round-trip, and the `doc_text`
full-text index finds them (DESIGN.md sections 7 and 12).

Needs Docker. Run with `uv run pytest -m neo4j`.
"""

from collections import Counter
from pathlib import Path

import pytest
from neo4j import Driver

from memex.config import load_config
from memex.graph.model import DocNode
from memex.graph.store import ensure_schema, label_of, replace_codebase
from memex.ingest import index_codebase

pytestmark = pytest.mark.neo4j

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
BATCH = index_codebase(load_config(FIXTURES / "memex.toml").get("layered_app"))
DOCS = [node for node in BATCH.nodes if isinstance(node, DocNode)]


@pytest.fixture
def stored(driver: Driver) -> Driver:
    ensure_schema(driver)
    replace_codebase(driver, BATCH)
    return driver


def test_every_doc_node_is_stored_with_all_its_properties(stored: Driver) -> None:
    rows, _, _ = stored.execute_query(
        "MATCH (d:Doc {codebase: 'layered_app'}) RETURN properties(d) AS props"
    )
    assert sorted((row["props"] for row in rows), key=lambda p: p["id"]) == sorted(
        (vars(doc) for doc in DOCS), key=lambda p: p["id"]
    )


def test_every_mention_is_stored_with_its_match(stored: Driver) -> None:
    rows, _, _ = stored.execute_query(
        "MATCH (d:Doc {codebase: 'layered_app'})-[m:MENTIONS]->(c) "
        "RETURN d.id AS source, c.id AS target, m.match AS match, labels(c)[0] AS label"
    )
    targets = {node.id: label_of(node) for node in BATCH.nodes}
    expected = {
        (e.source, e.target, e.match, targets[e.target])
        for e in BATCH.edges
        if e.kind == "MENTIONS"
    }
    assert {(r["source"], r["target"], r["match"], r["label"]) for r in rows} == expected
    assert Counter(r["label"] for r in rows) == {"Class": 6, "Module": 4, "Function": 3}


def test_full_text_search_finds_a_rule_and_its_mentions(stored: Driver) -> None:
    rows, _, _ = stored.execute_query(
        "CALL db.index.fulltext.queryNodes('doc_text', 'never call repository') "
        "YIELD node, score WITH node ORDER BY score DESC LIMIT 1 "
        "MATCH (node)-[m:MENTIONS]->(c) "
        "RETURN node.id AS doc, node.kind AS kind, collect([c.qualname, m.match]) AS mentions"
    )
    assert [row["doc"] for row in rows] == ["layered_app:doc:AGENTS.md#Layers"]
    assert rows[0]["kind"] == "agents"
    assert sorted(map(tuple, rows[0]["mentions"])) == [
        ("app._base.service.BaseService", "backtick_name"),
        ("app.repos.repository_factory.AllRepositories", "backtick_name"),
        ("app.routes", "path"),
    ]


def test_full_text_search_covers_heading_paths(stored: Driver) -> None:
    rows, _, _ = stored.execute_query(
        "CALL db.index.fulltext.queryNodes('doc_text', 'heading_path:\"Use repositories\"') "
        "YIELD node RETURN node.id AS doc ORDER BY doc"
    )
    adr = "layered_app:doc:docs/decisions/001-use-repositories.md"
    assert [row["doc"] for row in rows] == [f"{adr}#ADR 001: Use repositories", f"{adr}#Decision"]
