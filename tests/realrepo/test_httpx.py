"""Smoke tests on httpx: a differently shaped library indexed with defaults only.
DESIGN.md section 12.

Needs `uv run python scripts/fetch_codebases.py`. Run with `uv run pytest -m realrepo`.
"""

from pathlib import Path

import pytest

from memex.config import load_config
from memex.graph.model import ClassNode, DocNode, GraphBatch, ModuleNode
from memex.ingest import index_codebase

pytestmark = pytest.mark.realrepo

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def batch() -> GraphBatch:
    codebase = load_config(REPO_ROOT / "memex.toml").get("httpx")
    assert codebase.root.is_dir(), "run `uv run python scripts/fetch_codebases.py` first"
    assert not codebase.layers and not codebase.extractors, "httpx must use defaults only"
    return index_codebase(codebase)


def test_parses_with_zero_errors(batch: GraphBatch) -> None:
    assert batch.stats.parse_errors == ()
    assert batch.stats.files > 15


def test_no_duplicate_ids_and_no_dangling_edges(batch: GraphBatch) -> None:
    ids = [node.id for node in batch.nodes]
    dangling = [edge for edge in batch.edges if {edge.source, edge.target} - set(ids)]

    assert len(ids) == len(set(ids))
    assert dangling == []


def test_client_and_async_client_are_found(batch: GraphBatch) -> None:
    classes = {node.qualname for node in batch.nodes if isinstance(node, ClassNode)}

    assert {"httpx._client.Client", "httpx._client.AsyncClient"} <= classes


def test_underscore_private_folders_and_files_get_clean_labels(batch: GraphBatch) -> None:
    modules = {node.path: node for node in batch.nodes if isinstance(node, ModuleNode)}

    asgi = modules["httpx/_transports/asgi.py"]
    client = modules["httpx/_client.py"]
    assert (asgi.layer, asgi.domain) == ("transports", "asgi")
    assert (client.layer, client.domain) == ("root", "client")


def test_no_references_without_an_extractor(batch: GraphBatch) -> None:
    # httpx lists no extractors, so the extractor stage must add nothing.
    kinds = {edge.kind for edge in batch.edges}

    assert "INHERITS" in kinds
    assert "REFERENCES" not in kinds


def test_client_get_calls_client_request(batch: GraphBatch) -> None:
    # httpx/_client.py: Client.get returns self.request("GET", ...).
    get = "httpx:httpx._client.Client.get"
    calls = {
        (edge.target, edge.confidence)
        for edge in batch.edges
        if edge.kind == "CALLS" and edge.source == get
    }

    assert ("httpx:httpx._client.Client.request", "exact") in calls


def test_readme_and_docs_are_indexed_with_the_default_kind(batch: GraphBatch) -> None:
    docs = [node for node in batch.nodes if isinstance(node, DocNode)]
    paths = {doc.path for doc in docs}

    assert {"README.md", "docs/api.md", "docs/async.md"} <= paths
    assert all(path == "README.md" or path.startswith("docs/") for path in paths)
    assert {doc.kind for doc in docs} == {"doc"}  # httpx has no doc_kinds


def test_an_api_heading_in_backticks_mentions_its_class(batch: GraphBatch) -> None:
    # docs/api.md: "## `Client`"
    mentions = {
        (edge.target, edge.match)
        for edge in batch.edges
        if edge.kind == "MENTIONS" and edge.source == "httpx:doc:docs/api.md#Client"
    }

    assert ("httpx:httpx._client.Client", "backtick_name") in mentions
