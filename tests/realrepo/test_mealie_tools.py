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
    ChangeCheck,
    Citation,
    DocSearch,
    Guideline,
    Impact,
    SymbolSearch,
)

pytestmark = [pytest.mark.neo4j, pytest.mark.realrepo]

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = load_config(REPO_ROOT / "memex.toml")
SIZE_BUDGET = 4096
RECIPE_MODEL = "mealie.db.models.recipe.recipe.RecipeModel"

# check_change on three hand-written proposals (not the eval's q11 and q12), each checked by
# hand against vendor/mealie/AGENTS.md before the test was written.
GUIDE = "Mealie Development Guide for AI Agents > Critical Development Practices"
APP_SETTINGS = "Instantiate `AppSettings()` directly in a new service to read the base URL."
LOCALES = "Add a German translation by editing the de-DE locale files."
PIP = "Run the backend tests with pip and python directly."
# Ten distinct classes and functions, named explicitly: the most resolved symbols at once.
TEN = [
    "AppSettings",
    "RecipeModel",
    "AllRepositories",
    "RecipeService",
    "get_app_settings",
    "GroupAIProviderController",
    "OpenAIService",
    "IngredientParserController",
    "RegisteredParser",
    "ABCIngredientParser",
]
# Ten short names shared by several classes: the largest result a description can ask for.
MANY_NAMES = (
    "Change `get_one`, `create`, `update`, `delete`, `__init__`, `get_all`, `get`, `save`, "
    "`run` and `validate`."
)


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
        ("check_change", {"codebase": "mealie", "proposal": {"description": APP_SETTINGS}}),
        ("check_change", {"codebase": "mealie", "proposal": {"description": LOCALES}}),
        ("check_change", {"codebase": "mealie", "proposal": {"description": PIP}}),
        ("check_change", {"codebase": "mealie", "proposal": {"description": MANY_NAMES}}),
        (
            "check_change",
            {
                "codebase": "mealie",
                "proposal": {"description": "Refactor it.", "symbols": ["AllRepositories"]},
            },
        ),
        (
            "check_change",
            {"codebase": "mealie", "proposal": {"description": "Refactor.", "symbols": TEN}},
        ),
    ],
)
def test_results_fit_the_size_budget_at_default_limits(
    server: FastMCP, name: str, args: dict[str, Any]
) -> None:
    (text,) = call(server, name, args).content

    assert len(text.text.encode()) < SIZE_BUDGET


def check(server: FastMCP, description: str) -> ChangeCheck:
    proposal = {"description": description}
    result = call(server, "check_change", {"codebase": "mealie", "proposal": proposal})
    return ChangeCheck.model_validate(result.structured_content)


def cited(checked: ChangeCheck) -> list[tuple[str, str, int, int, str]]:
    return [
        (g.stance, g.citation.path, g.citation.start_line, g.citation.end_line, g.matched_on)
        for g in checked.guidelines
    ]


def test_instantiating_app_settings_is_forbidden_by_a_mention(server: FastMCP) -> None:
    checked = check(server, APP_SETTINGS)

    assert [ref.qualname for ref in checked.resolved_symbols] == [
        "mealie.core.settings.settings.AppSettings"
    ]
    assert checked.guidelines[0] == Guideline(
        stance="forbids",
        quote="Never instantiate `AppSettings()` directly",
        citation=Citation(
            path="AGENTS.md",
            heading_path=f"{GUIDE} > Python Backend",
            start_line=121,
            end_line=121,
        ),
        matched_on="mention",
    )


def test_editing_another_locale_is_forbidden_by_search(server: FastMCP) -> None:
    checked = check(server, LOCALES)

    assert checked.resolved_symbols == []
    assert ("forbids", "AGENTS.md", 144, 144, "search") in cited(checked)
    rule = next(g for g in checked.guidelines if g.citation.start_line == 144)
    assert rule.citation.heading_path == f"{GUIDE} > Frontend"
    assert "en-US" in rule.quote


def test_running_python_through_uv_is_encouraged_by_search(server: FastMCP) -> None:
    checked = check(server, PIP)

    assert checked.guidelines[0] == Guideline(
        stance="encourages",
        quote="**Always use `uv` for Python commands** (not `python` or `pip`):",
        citation=Citation(
            path="AGENTS.md",
            heading_path=f"{GUIDE} > Python Backend",
            start_line=100,
            end_line=100,
        ),
        matched_on="search",
    )


def test_many_ambiguous_names_share_the_candidate_cap(server: FastMCP) -> None:
    checked = check(server, MANY_NAMES)

    counts = [len(a.candidates) for a in checked.ambiguous]
    assert all(count in (0, 2, 3) for count in counts)  # never a single candidate
    assert sum(counts) <= 8
    assert counts[-1] == 0  # past the total: listed, with no candidates
