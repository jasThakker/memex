"""MCP contract tests (DESIGN.md sections 10 and 12): the FastMCP in-memory client calls every
tool and checks names, schemas, defaults, scope errors, ambiguity, the size budget and that
nothing writes. Needs Docker. Run with `uv run pytest -m neo4j`.
"""

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from neo4j import Driver
from pydantic import BaseModel

from memex.config import load_config
from memex.graph.model import DocNode, Edge, code_id, doc_id
from memex.graph.store import ensure_schema, replace_codebase
from memex.ingest.code import index_code
from memex.mcp.server import build_server
from memex.query import calls, codebases, docs, impact, symbols
from memex.query.models import CallGraph, CodebaseList, DocSearch, Impact, SymbolSearch

pytestmark = pytest.mark.neo4j

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGISTRY = load_config(FIXTURES / "memex.toml")
SIZE_BUDGET = 4096  # bytes of the JSON text an agent receives per call, at default limits

TOOLS: dict[str, type[BaseModel]] = {
    "list_codebases": CodebaseList,
    "find_symbol": SymbolSearch,
    "callers": CallGraph,
    "callees": CallGraph,
    "impact_of": Impact,
    "search_docs": DocSearch,
}
# One call per tool at its default limits, and the query function it must match exactly.
CALLS: list[tuple[str, dict[str, Any], Any]] = [
    ("list_codebases", {}, lambda d: codebases.list_codebases(d, REGISTRY)),
    (
        "find_symbol",
        {"codebase": "layered_app", "name": "get"},
        lambda d: symbols.find_symbol(d, "layered_app", "get"),
    ),
    (
        "callers",
        {"codebase": "layered_app", "symbol": "AllRepositories.__init__"},
        lambda d: calls.callers(d, "layered_app", "AllRepositories.__init__"),
    ),
    (
        "callees",
        {"codebase": "layered_app", "symbol": "get_order"},
        lambda d: calls.callees(d, "layered_app", "get_order"),
    ),
    (
        "impact_of",
        {"codebase": "layered_app", "symbol": "BaseService"},
        lambda d: impact.impact_of(d, "layered_app", "BaseService"),
    ),
    (
        "search_docs",
        {"codebase": "layered_app", "query": "services"},
        lambda d: docs.search_docs(d, "layered_app", "services"),
    ),
]


def layered_with_a_doc() -> Any:
    batch = index_code(REGISTRY.get("layered_app"))
    node_id = doc_id("layered_app", "docs/services.md", "services")
    doc = DocNode(
        id=node_id,
        codebase="layered_app",
        path="docs/services.md",
        heading_path="Services",
        anchor="services",
        text="Services read data through the injected repositories.",
        start_line=1,
        end_line=3,
    )
    mention = Edge(
        kind="MENTIONS",
        source=node_id,
        target=code_id("layered_app", "app._base.service.BaseService"),
        match="qualname",
    )
    return replace(batch, nodes=(*batch.nodes, doc), edges=(*batch.edges, mention))


@pytest.fixture
def server(driver: Driver) -> FastMCP:
    """layered_app indexed with one doc section; plainrepo registered but not indexed."""
    ensure_schema(driver)
    replace_codebase(driver, layered_with_a_doc())
    return build_server(driver, REGISTRY)


def run(server: FastMCP, action: Any) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await action(client)

    return asyncio.run(go())


def call(server: FastMCP, name: str, args: dict[str, Any]) -> Any:
    return run(server, lambda client: client.call_tool(name, args))


def tools(server: FastMCP) -> dict[str, Any]:
    return {tool.name: tool for tool in run(server, lambda client: client.list_tools())}


def test_the_tools_are_those_of_the_design(server: FastMCP) -> None:
    # check_change arrives in Phase 6; module_summary is stretch.
    assert set(tools(server)) == set(TOOLS)


def test_every_tool_is_read_only_and_described(server: FastMCP) -> None:
    for tool in tools(server).values():
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.description


def test_output_schemas_are_the_contract_models(server: FastMCP) -> None:
    for name, tool in tools(server).items():
        assert set(tool.output_schema["properties"]) == set(TOOLS[name].model_fields), name


def test_every_tool_except_list_codebases_requires_a_codebase(server: FastMCP) -> None:
    for name, tool in tools(server).items():
        required = tool.input_schema.get("required", [])
        assert ("codebase" in required) == (name != "list_codebases"), name


def test_defaults_are_the_documented_limits(server: FastMCP) -> None:
    def defaults(name: str) -> dict[str, Any]:
        properties = tools(server)[name].input_schema["properties"]
        return {key: value["default"] for key, value in properties.items() if "default" in value}

    assert defaults("find_symbol") == {"kind": "any", "limit": 10}
    assert defaults("callers") == {"depth": 1, "limit": 12}
    assert defaults("callees") == {"depth": 1, "limit": 12}
    assert defaults("impact_of") == {"max_depth": 3, "limit": 8}
    assert defaults("search_docs") == {"limit": 5}


@pytest.mark.parametrize(("name", "args", "direct"), CALLS, ids=[c[0] for c in CALLS])
def test_each_tool_returns_what_its_query_function_returns(
    server: FastMCP, driver: Driver, name: str, args: dict[str, Any], direct: Any
) -> None:
    result = call(server, name, args)

    assert TOOLS[name].model_validate(result.structured_content) == direct(driver)


@pytest.mark.parametrize(("name", "args", "direct"), CALLS, ids=[c[0] for c in CALLS])
def test_results_fit_the_size_budget_at_default_limits(
    server: FastMCP, name: str, args: dict[str, Any], direct: Any
) -> None:
    result = call(server, name, args)

    (text,) = result.content  # the compact JSON text sent to the agent
    assert len(text.text.encode()) < SIZE_BUDGET


@pytest.mark.parametrize("name", [name for name in TOOLS if name != "list_codebases"])
def test_an_unknown_codebase_is_an_error_listing_the_registered_ones(
    server: FastMCP, name: str
) -> None:
    args = {"codebase": "nope", "name": "x", "symbol": "x", "query": "x"}
    schema = tools(server)[name].input_schema["properties"]

    with pytest.raises(ToolError, match="registered codebases: layered_app, plainrepo"):
        call(server, name, {key: value for key, value in args.items() if key in schema})


def test_a_registered_codebase_that_is_not_indexed_is_an_error(server: FastMCP) -> None:
    with pytest.raises(ToolError, match="memex index plainrepo"):
        call(server, "find_symbol", {"codebase": "plainrepo", "name": "x"})


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("find_symbol", {"codebase": "layered_app", "name": "x", "limit": 0}),
        ("callers", {"codebase": "layered_app", "symbol": "get_order", "depth": 9}),
        ("search_docs", {"codebase": "layered_app", "query": "  "}),
    ],
)
def test_bad_arguments_are_tool_errors_with_the_reason(
    server: FastMCP, name: str, args: dict[str, Any]
) -> None:
    with pytest.raises(ToolError, match="must"):
        call(server, name, args)


def test_an_ambiguous_name_returns_candidates(server: FastMCP) -> None:
    result = call(server, "callers", {"codebase": "layered_app", "symbol": "get_one"})
    graph = CallGraph.model_validate(result.structured_content)

    assert graph.symbol is None
    assert len(graph.candidates) == 2


def test_no_tool_writes(server: FastMCP, driver: Driver) -> None:
    def counts() -> tuple[int, int]:
        rows, _, _ = driver.execute_query(
            "MATCH (n) OPTIONAL MATCH (n)-[r]->() RETURN count(DISTINCT n) AS n, count(r) AS r"
        )
        return rows[0]["n"], rows[0]["r"]

    before = counts()
    for name, args, _ in CALLS:
        call(server, name, args)

    assert counts() == before
