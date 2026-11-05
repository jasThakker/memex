"""search_docs against the `doc_text` full-text index (DESIGN.md section 10).

Doc sections and their MENTIONS edges are added by hand, so this does not depend on the docs
ingest. Needs Docker. Run with `uv run pytest -m neo4j`.
"""

from dataclasses import replace
from pathlib import Path

import pytest
from neo4j import Driver

from memex.config import load_config
from memex.graph.model import DocNode, Edge, GraphBatch, code_id, doc_id
from memex.graph.store import ensure_schema, replace_codebase
from memex.ingest.code import index_code
from memex.query.docs import search_docs

pytestmark = pytest.mark.neo4j

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGISTRY = load_config(FIXTURES / "memex.toml")

USER_OUT = "app.schema.user.UserOut"
BASE = "app._base.service.BaseService"
ORDER_SERVICE = "app.services.order_services.order_service.OrderService"

# (codebase, path, anchor, heading_path, kind, text, start_line, mentions)
DOCS = [
    (
        "layered_app",
        "docs/contributing.md",
        "generated-types",
        "Contributing > Generated types",
        "contributor",
        "Never edit the generated types by hand. Run the generator instead.",
        10,
        [USER_OUT],
    ),
    (
        "layered_app",
        "docs/services.md",
        "services",
        "Services",
        "doc",
        "Services read data through the injected repositories. Keep business logic in services.",
        1,
        [ORDER_SERVICE, BASE],
    ),
    (
        "layered_app",
        "docs/routes.md",
        "routes",
        "Routes",
        "doc",
        "Routes call services and return schemas. Use self.repos.get_one() for one row.",
        1,
        [],
    ),
    (
        "plainrepo",
        "README.md",
        "readme",
        "Readme",
        "doc",
        "Never edit generated files.",
        1,
        [],
    ),
]


def batch_with_docs(name: str) -> GraphBatch:
    batch = index_code(REGISTRY.get(name))
    nodes, edges = [], []
    for codebase, path, anchor, heading, kind, text, line, mentions in DOCS:
        if codebase != name:
            continue
        node_id = doc_id(codebase, path, anchor)
        nodes.append(
            DocNode(
                id=node_id,
                codebase=codebase,
                path=path,
                heading_path=heading,
                anchor=anchor,
                text=text,
                start_line=line,
                end_line=line + 4,
                kind=kind,
            )
        )
        edges.extend(
            Edge(kind="MENTIONS", source=node_id, target=code_id(codebase, q), match="qualname")
            for q in mentions
        )
    return replace(batch, nodes=batch.nodes + tuple(nodes), edges=batch.edges + tuple(edges))


@pytest.fixture
def indexed(driver: Driver) -> Driver:
    ensure_schema(driver)
    replace_codebase(driver, batch_with_docs("layered_app"))
    replace_codebase(driver, batch_with_docs("plainrepo"))
    return driver


def test_a_hit_carries_its_location_kind_snippet_and_mentions(indexed: Driver) -> None:
    result = search_docs(indexed, "layered_app", "generated types")

    assert result.codebase == "layered_app"
    assert result.query == "generated types"
    hit = result.hits[0]
    assert hit.path == "docs/contributing.md"
    assert hit.heading_path == "Contributing > Generated types"
    assert hit.kind == "contributor"
    assert (hit.start_line, hit.end_line) == (10, 14)
    assert "generated types" in hit.snippet
    assert hit.mentions == [USER_OUT]
    assert hit.score > 0
    assert result.truncated is False


def test_mentions_are_sorted_and_hits_are_ordered_by_score(indexed: Driver) -> None:
    result = search_docs(indexed, "layered_app", "services")

    assert [hit.path for hit in result.hits][0] == "docs/services.md"  # says it twice
    assert result.hits[0].mentions == [BASE, ORDER_SERVICE]
    scores = [hit.score for hit in result.hits]
    assert scores == sorted(scores, reverse=True)


def test_headings_are_searched(indexed: Driver) -> None:
    # "Contributing" is only in the heading path, not in the text.
    result = search_docs(indexed, "layered_app", "contributing")

    assert [hit.path for hit in result.hits] == ["docs/contributing.md"]


def test_hits_stay_inside_the_named_codebase(indexed: Driver) -> None:
    layered = search_docs(indexed, "layered_app", "generated")
    plain = search_docs(indexed, "plainrepo", "generated")

    assert [hit.path for hit in layered.hits] == ["docs/contributing.md"]
    assert [hit.path for hit in plain.hits] == ["README.md"]


def test_the_codebase_filter_comes_before_the_limit(indexed: Driver) -> None:
    # plainrepo's short README would outscore contributing.md if the limit came first.
    result = search_docs(indexed, "layered_app", "generated", limit=1)

    assert [hit.path for hit in result.hits] == ["docs/contributing.md"]
    assert result.truncated is False


@pytest.mark.parametrize(
    # `and` would match routes.md ("services and return"), so the operator word is OR here.
    "query",
    ['"generated', "generated)", "generated OR", "[generated]~", "generated:*"],
)
def test_lucene_syntax_in_a_query_is_searched_as_text(indexed: Driver, query: str) -> None:
    result = search_docs(indexed, "layered_app", query)

    assert [hit.path for hit in result.hits] == ["docs/contributing.md"]


def test_a_code_expression_can_be_searched(indexed: Driver) -> None:
    # Unescaped, the parentheses would be a Lucene syntax error.
    result = search_docs(indexed, "layered_app", "self.repos.get_one()")

    assert [hit.path for hit in result.hits] == ["docs/routes.md"]
    assert "self.repos.get_one()" in result.hits[0].snippet


@pytest.mark.parametrize("query", ["()", "--", "!?", '"'])
def test_a_query_of_punctuation_only_has_no_hits(indexed: Driver, query: str) -> None:
    result = search_docs(indexed, "layered_app", query)

    assert result.hits == []
    assert result.truncated is False


def test_hits_are_truncated_at_the_limit(indexed: Driver) -> None:
    result = search_docs(indexed, "layered_app", "services", limit=1)

    assert len(result.hits) == 1
    assert result.truncated is True


def test_no_match_gives_no_hits(indexed: Driver) -> None:
    result = search_docs(indexed, "layered_app", "xylophone")

    assert result.hits == []
    assert result.truncated is False


@pytest.mark.parametrize(
    ("query", "limit"), [("", 5), ("   ", 5), ("x", 0), ("x", 201), ("word " * 101, 5)]
)
def test_bad_arguments_are_an_error(indexed: Driver, query: str, limit: int) -> None:
    with pytest.raises(ValueError):
        search_docs(indexed, "layered_app", query, limit=limit)
