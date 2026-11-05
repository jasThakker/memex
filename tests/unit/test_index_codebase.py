from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from memex.config import Codebase, load_config
from memex.graph.model import CodebaseNode, Node
from memex.graph.store import label_of, validate
from memex.ingest import index_codebase
from memex.ingest.code import index_code
from memex.ingest.docs import index_docs

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAYERED_APP = load_config(FIXTURES / "memex.toml").get("layered_app")


def without_time(nodes: Sequence[Node]) -> list[Node]:
    return [replace(n, indexed_at="") if isinstance(n, CodebaseNode) else n for n in nodes]


def test_index_codebase_is_the_code_batch_plus_the_docs() -> None:
    batch = index_codebase(LAYERED_APP)
    code = index_code(LAYERED_APP)
    docs = index_docs(LAYERED_APP, code.nodes)

    assert batch.codebase == "layered_app"
    assert without_time(batch.nodes) == without_time([*code.nodes, *docs.nodes])
    assert batch.edges == (*code.edges, *docs.edges)
    assert batch.stats == code.stats
    # From the fixture docs: 7 heading chunks, 13 mentions (tests/unit/test_mentions.py)
    assert Counter(label_of(node) for node in batch.nodes)["Doc"] == 7
    assert Counter(edge.kind for edge in batch.edges)["MENTIONS"] == 13


def test_the_combined_batch_passes_store_validation() -> None:
    validate(index_codebase(LAYERED_APP))  # unique ids, codebase prefix, no dangling MENTIONS


def test_doc_parse_errors_join_the_code_parse_errors(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "bad.md").write_bytes(b"\xff")
    codebase = Codebase(name="tmp", root=tmp_path, packages=("pkg",), docs=("*.md",))

    batch = index_codebase(codebase)

    assert [error.path for error in batch.stats.parse_errors] == ["pkg/__init__.py", "bad.md"]
    node = next(n for n in batch.nodes if isinstance(n, CodebaseNode))
    assert node.parse_errors == 2  # code and doc files, so it matches the listed errors
