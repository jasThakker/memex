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
from memex.query.models import (
    CallGraph,
    DocSearch,
    Impact,
    SymbolSearch,
)

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
    # a class reached by REFERENCES is a leaf: REFERENCES is only ever a dependent's own edge
    assert all(step.edge != "REFERENCES" for d in dependents(impact) for step in d.path[1:])


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


def test_calls_through_typed_attributes_reach_the_service(server: FastMCP) -> None:
    # The four callers eval/impact_check.md found missing, each through a typed attribute:
    # a cached_property's return annotation (on a base class), `self.x = C(...)` in
    # __init__, and an annotated __init__ parameter.
    result = call(
        server,
        "callers",
        {
            "codebase": "mealie",
            "symbol": "mealie.services.recipe.recipe_service.RecipeService.create_one",
            "limit": 50,
        },
    )
    graph = CallGraph.model_validate(result.structured_content)

    found = {(c.function.qualname, c.confidence) for c in graph.calls}
    assert {
        (
            "mealie.routes.recipe.recipe_crud_routes.RecipeController._finish_recipe_from_web",
            "exact",
        ),
        ("mealie.routes.recipe.recipe_crud_routes.RecipeController.create_one", "exact"),
        (
            "mealie.services.migrations._migration_base.BaseMigrator.import_recipes_to_database",
            "exact",
        ),
        ("mealie.services.scraper.recipe_bulk_scraper.RecipeBulkScraperService.scrape", "exact"),
    } <= found


def test_fastapi_dependencies_reach_their_users(server: FastMCP) -> None:
    # The five direct dependents eval/impact_check.md found missing: `Depends(...)` in a
    # parameter default, a class attribute and a router's __init__ (USES, ADR-003).
    result = call(
        server,
        "impact_of",
        {
            "codebase": "mealie",
            "symbol": "mealie.core.dependencies.dependencies.get_current_user",
            "max_depth": 1,
            "limit": 50,
        },
    )
    impact = Impact.model_validate(result.structured_content)

    by_uses = {d.symbol.qualname for d in dependents(impact) if d.path[0].edge == "USES"}
    assert {
        "mealie.core.dependencies.dependencies.get_admin_user",
        "mealie.routes.auth.auth.refresh_token",
        "mealie.routes._base.routers.UserAPIRouter.__init__",
        "mealie.routes._base.permissions.RequirePermission.__call__",
        "mealie.routes._base.base_controllers.BaseUserController",
    } <= by_uses


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


# ADR-004: with no check_change tool, the agent finds a documented rule with impact_of and
# search_docs. Checked by hand against vendor/mealie/AGENTS.md line 121.
RULE_SECTION = (
    "AGENTS.md",
    "Mealie Development Guide for AI Agents > Critical Development Practices > Python Backend",
)


def test_impact_of_cites_the_rule_section_about_a_symbol(server: FastMCP) -> None:
    result = call(server, "impact_of", {"codebase": "mealie", "symbol": "AppSettings"})
    impact = Impact.model_validate(result.structured_content)

    sections = [(doc.path, doc.heading_path) for doc in impact.docs]
    assert sections[0] == RULE_SECTION
    assert impact.docs[0].start_line <= 121 <= impact.docs[0].end_line


def test_search_docs_finds_the_rule_from_the_proposal_text(server: FastMCP) -> None:
    query = "Instantiate AppSettings directly in a new service"
    result = call(server, "search_docs", {"codebase": "mealie", "query": query})
    hits = DocSearch.model_validate(result.structured_content).hits

    assert (hits[0].path, hits[0].heading_path) == RULE_SECTION
    assert "Never instantiate `AppSettings()` directly" in hits[0].snippet
