"""The MCP tools on httpx, indexed with defaults only: the same tools answer a differently
shaped library with no code change (DESIGN.md sections 4, 12 and 15).

Needs Docker and `uv run python scripts/fetch_codebases.py`. Run with
`uv run pytest -m "neo4j and realrepo"`.
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
CLIENT = "httpx._client.Client"


@pytest.fixture(scope="module")
def server(neo4j_driver: Driver) -> Iterator[FastMCP]:
    codebase = REGISTRY.get("httpx")
    assert codebase.root.is_dir(), "run `uv run python scripts/fetch_codebases.py` first"
    assert not codebase.layers and not codebase.extractors, "httpx must use defaults only"
    neo4j_driver.execute_query("MATCH (n) DETACH DELETE n")
    ensure_schema(neo4j_driver)
    replace_codebase(neo4j_driver, index_codebase(codebase))
    yield build_server(neo4j_driver, REGISTRY)


def call(server: FastMCP, name: str, args: dict[str, Any]) -> Any:
    async def go() -> Any:
        async with Client(server) as client:
            return await client.call_tool(name, args)

    return asyncio.run(go())


def test_client_and_async_client_are_found(server: FastMCP) -> None:
    for name in ("Client", "AsyncClient"):
        result = call(server, "find_symbol", {"codebase": "httpx", "name": name})
        found = SymbolSearch.model_validate(result.structured_content).symbols

        assert found[0].qualname == f"httpx._client.{name}"
        assert found[0].kind == "class"


def test_client_get_is_a_caller_of_client_request(server: FastMCP) -> None:
    result = call(server, "callers", {"codebase": "httpx", "symbol": "Client.request"})
    graph = CallGraph.model_validate(result.structured_content)

    assert graph.symbol is not None and graph.symbol.qualname == f"{CLIENT}.request"
    hops = {(hop.function.qualname, hop.confidence) for hop in graph.calls}
    assert (f"{CLIENT}.get", "exact") in hops


def test_what_depends_on_the_client(server: FastMCP) -> None:
    result = call(server, "impact_of", {"codebase": "httpx", "symbol": CLIENT, "limit": 200})
    impact = Impact.model_validate(result.structured_content)

    assert impact.total > 0
    layers = {group.layer for group in impact.layers}
    assert "root" in layers  # default layers: modules directly in the package are `root`


def test_the_readme_and_docs_are_searchable(server: FastMCP) -> None:
    result = call(server, "search_docs", {"codebase": "httpx", "query": "timeout"})
    hits = DocSearch.model_validate(result.structured_content).hits

    assert hits
    assert all(hit.path == "README.md" or hit.path.startswith("docs/") for hit in hits)
    assert {hit.kind for hit in hits} == {"doc"}  # no doc_kinds config


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("find_symbol", {"codebase": "httpx", "name": "Client"}),
        ("callers", {"codebase": "httpx", "symbol": "Client.request"}),
        ("callees", {"codebase": "httpx", "symbol": "Client.send"}),
        ("impact_of", {"codebase": "httpx", "symbol": CLIENT}),
        ("search_docs", {"codebase": "httpx", "query": "timeout"}),
    ],
)
def test_results_fit_the_size_budget_at_default_limits(
    server: FastMCP, name: str, args: dict[str, Any]
) -> None:
    (text,) = call(server, name, args).content

    assert len(text.text.encode()) < SIZE_BUDGET
