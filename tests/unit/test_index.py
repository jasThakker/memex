from collections import Counter
from pathlib import Path

from memex.config import Codebase, load_config
from memex.graph.model import (
    ClassNode,
    CodebaseNode,
    ExternalNode,
    FunctionNode,
    GraphBatch,
    ModuleNode,
)
from memex.ingest.code import index_code

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGISTRY = load_config(FIXTURES / "memex.toml")
LAYERED = index_code(REGISTRY.get("layered_app"))


def by_qualname(batch: GraphBatch) -> dict[str, ModuleNode | ClassNode | FunctionNode]:
    return {
        node.qualname: node
        for node in batch.nodes
        if isinstance(node, ModuleNode | ClassNode | FunctionNode)
    }


def make_codebase(tmp_path: Path, files: dict[str, str]) -> Codebase:
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text, encoding="utf-8")
    return Codebase(name="lib", root=tmp_path, packages=("pkg",))


def test_batch_starts_with_the_codebase_node() -> None:
    codebase = REGISTRY.get("layered_app")
    node = LAYERED.nodes[0]

    assert LAYERED.codebase == "layered_app"
    assert isinstance(node, CodebaseNode)
    assert (node.id, node.name, node.root) == ("layered_app", "layered_app", str(codebase.root))
    assert node.extractors == ("sqlalchemy",)
    assert node.parse_errors == 0
    assert node.indexed_at


def test_every_code_node_carries_its_module_labels() -> None:
    nodes = by_qualname(LAYERED)

    assert len([node for node in nodes.values() if isinstance(node, ModuleNode)]) == 27
    service = "app.services.user_services.user_service"
    for qualname in (service, f"{service}.UserService", f"{service}.UserService.get"):
        assert (nodes[qualname].layer, nodes[qualname].domain) == ("services", "user")
    assert (nodes["app.main.create_app"].layer, nodes["app.main.create_app"].domain) == (
        "root",
        "main",
    )
    assert all(node.layer for node in nodes.values())


def test_batch_holds_defines_and_imports_edges_and_externals() -> None:
    kinds = Counter(edge.kind for edge in LAYERED.edges)
    externals = {node.name for node in LAYERED.nodes if isinstance(node, ExternalNode)}

    assert set(kinds) == {"DEFINES", "IMPORTS"}
    assert kinds["DEFINES"] == len(by_qualname(LAYERED)) - 27  # one per class or function
    assert "pydantic.BaseModel" in externals


def test_node_ids_are_unique() -> None:
    ids = [node.id for node in LAYERED.nodes]

    assert len(ids) == len(set(ids))


def test_stats_count_files_and_modules_per_layer_and_domain() -> None:
    stats = LAYERED.stats

    assert stats.files == 27
    assert stats.parse_errors == ()
    assert stats.layers == {
        "root": 3,
        "base": 2,
        "db": 1,
        "db_models": 4,
        "repos": 4,
        "routes": 5,
        "schema": 3,
        "services": 5,
    }
    assert stats.domains == {
        "user": 7,
        "order": 7,
        "version": 1,
        "main": 1,
        "service": 1,
        "model_base": 1,
        "factory": 1,
    }


def test_plainrepo_has_no_references_without_an_extractor() -> None:
    batch = index_code(REGISTRY.get("plainrepo"))

    assert batch.stats.files == 10
    assert {edge.kind for edge in batch.edges} == {"DEFINES", "IMPORTS"}


def test_a_file_that_fails_to_parse_is_counted_and_the_rest_is_indexed(tmp_path: Path) -> None:
    batch = index_code(
        make_codebase(tmp_path, {"pkg/__init__.py": "", "pkg/bad.py": "def broken(:\n"})
    )

    assert batch.stats.files == 2
    assert [error.path for error in batch.stats.parse_errors] == ["pkg/bad.py"]
    codebase_node = batch.nodes[0]
    assert isinstance(codebase_node, CodebaseNode) and codebase_node.parse_errors == 1
    assert set(by_qualname(batch)) == {"pkg"}


def test_a_definition_that_clashes_with_a_submodule_is_dropped(tmp_path: Path) -> None:
    batch = index_code(
        make_codebase(
            tmp_path,
            {"pkg/__init__.py": "def utils(): ...\n", "pkg/utils.py": "def helper(): ...\n"},
        )
    )
    ids = [node.id for node in batch.nodes]

    assert len(ids) == len(set(ids))
    assert isinstance(by_qualname(batch)["pkg.utils"], ModuleNode)
    assert batch.stats.dropped_duplicates == ("lib:pkg.utils",)
    assert not [edge for edge in batch.edges if edge.kind == "DEFINES" and edge.source == "lib:pkg"]
