"""The MCP tools on Mealie, the primary benchmark (DESIGN.md sections 10, 12 and 15).

Mealie is indexed once into the test Neo4j and every tool is called through the in-memory MCP
client, so results and sizes are what an agent receives. Needs Docker and
`uv run python scripts/fetch_codebases.py`. Run with `uv run pytest -m "neo4j and realrepo"`.
"""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from neo4j import Driver

from memex.config import load_config
from memex.graph.store import ensure_schema, replace_codebase
from memex.ingest import index_codebase
from memex.mcp.server import build_server
from memex.query.models import CallGraph, DocSearch, Impact, SymbolSearch

pytestmark = [pytest.mark.neo4j, pytest.mark.realrepo]

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = load_config(REPO_ROOT / "memex.toml")
SIZE_BUDGET = 4096
RECIPE_MODEL = "mealie.db.models.recipe.recipe.RecipeModel"


@pytest.fixture(scope="module")
def server(neo4j_driver: Driver) -> Iterator[FastMCP]:
    codebase = REGISTRY.get("mealie")
    assert codebase.root.is_dir(), "run `uv run python scripts/fetch_codebases.py` first"
    neo4j_driver.execute_query("MATCH (n) DETACH DELETE n")
    ensure_schema(neo4j_driver)
    replace_codebase(neo4j_driver, index_codebase(codebase))
    yield build_server(neo4j_driver, REGISTRY)


def call(server: FastMCP, name: str, args: dict[str, Any]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await client.call_tool(name, args)

    return asyncio.run(go())


def dependents(impact: Impact) -> list[Any]:
    return [d for group in impact.layers for d in group.dependents]


def test_what_depends_on_recipe_model(server: FastMCP) -> None:
    result = call(
        server, "impact_of", {"codebase": "mealie", "symbol": "RecipeModel", "limit": 200}
    )
    impact = Impact.model_validate(result.structured_content)

    assert impact.symbol is not None and impact.symbol.qualname == RECIPE_MODEL
    referencing = [d for d in dependents(impact) if d.path[0].edge == "REFERENCES"]
    assert len(referencing) >= 10  # the sqlalchemy extractor found 34 REFERENCES into it
    assert {d.symbol.layer for d in referencing} == {"db_models"}
    assert {"db_models", "repos"} <= {group.layer for group in impact.layers}
    assert impact.total >= len(dependents(impact))


def test_the_generated_types_rule_is_found_by_search(server: FastMCP) -> None:
    result = call(
        server,
        "search_docs",
        {"codebase": "mealie", "query": "never manually edit generated types"},
    )
    hits = DocSearch.model_validate(result.structured_content).hits

    top = hits[0]
    assert (top.path, top.kind) == ("AGENTS.md", "agents")
    assert top.heading_path.endswith("Backend Architecture (mealie/)")
    assert "mealie.repos.repository_factory.AllRepositories" in top.mentions


def test_a_shared_method_name_returns_candidates_not_a_guess(server: FastMCP) -> None:
    result = call(server, "callers", {"codebase": "mealie", "symbol": "get_one"})
    graph = CallGraph.model_validate(result.structured_content)

    assert graph.symbol is None
    assert len(graph.candidates) == 12  # the default limit; Mealie has 31
    assert graph.truncated is True


def test_find_symbol_puts_the_class_first(server: FastMCP) -> None:
    result = call(server, "find_symbol", {"codebase": "mealie", "name": "RecipeModel"})
    found = SymbolSearch.model_validate(result.structured_content).symbols

    assert found[0].qualname == RECIPE_MODEL


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("list_codebases", {}),
        ("find_symbol", {"codebase": "mealie", "name": "Recipe"}),
        ("callers", {"codebase": "mealie", "symbol": "get_one"}),
        ("callers", {"codebase": "mealie", "symbol": "AllRepositories.__init__"}),
        ("callees", {"codebase": "mealie", "symbol": "RecipeService.create_one"}),
        ("impact_of", {"codebase": "mealie", "symbol": "RecipeModel"}),
        ("impact_of", {"codebase": "mealie", "symbol": "AllRepositories"}),
        ("search_docs", {"codebase": "mealie", "query": "database migration alembic"}),
    ],
)
def test_results_fit_the_size_budget_at_default_limits(
    server: FastMCP, name: str, args: dict[str, Any]
) -> None:
    (text,) = call(server, name, args).content

    assert len(text.text.encode()) < SIZE_BUDGET
