import os
import re
from pathlib import Path

import pytest

from memex.config import Codebase, ConfigError, load_config
from memex.graph.model import DocNode, ParseError
from memex.ingest.docs import index_docs
from memex.ingest.docs.loader import load_docs

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGISTRY = load_config(FIXTURES / "memex.toml")
LAYERED_APP = REGISTRY.get("layered_app")
ADR = "docs/decisions/001-use-repositories.md"


def test_docs_globs_expand_sorted_with_the_first_matching_kind() -> None:
    files, errors = load_docs(LAYERED_APP)
    assert [(f.path, f.kind) for f in files] == [
        ("AGENTS.md", "agents"),
        (ADR, "adr"),  # also matches "docs/**"; the first glob in the table wins
        ("docs/guide.md", "guide"),
    ]
    assert errors == []


def test_without_doc_kinds_every_doc_gets_kind_doc() -> None:
    files, _ = load_docs(REGISTRY.get("plainrepo"))
    assert [(f.path, f.kind) for f in files] == [("README.md", "doc")]


def test_a_file_matched_by_two_globs_is_loaded_once() -> None:
    codebase = LAYERED_APP.model_copy(update={"docs": ("*.md", "AGENTS.md")})
    files, _ = load_docs(codebase)
    assert [f.path for f in files] == ["AGENTS.md"]


@pytest.mark.parametrize("pattern", ["CONTRIBUTING.md", "app/routes/*"])
def test_a_glob_matching_no_markdown_file_is_a_config_error(pattern: str) -> None:
    codebase = LAYERED_APP.model_copy(update={"docs": ("AGENTS.md", pattern)})
    with pytest.raises(ConfigError, match=re.escape(f"docs glob {pattern!r}")):
        load_docs(codebase)


def test_a_doc_that_is_not_utf8_is_recorded_and_skipped(tmp_path: Path) -> None:
    (tmp_path / "good.md").write_text("# Good\n", encoding="utf-8")
    (tmp_path / "bad.md").write_bytes(b"# Bad \xff\n")
    codebase = Codebase(name="tmp", root=tmp_path, packages=("pkg",), docs=("*.md",))
    files, errors = load_docs(codebase)
    assert [f.path for f in files] == ["good.md"]
    assert len(errors) == 1
    assert errors[0].path == "bad.md"
    assert errors[0].line is None
    assert "UTF-8" in errors[0].message


def test_index_docs_turns_each_chunk_into_a_doc_node() -> None:
    result = index_docs(LAYERED_APP, ())
    assert [node.id for node in result.nodes] == [
        "layered_app:doc:AGENTS.md#Agent Guide",
        "layered_app:doc:AGENTS.md#Layers",
        "layered_app:doc:AGENTS.md#Database",
        f"layered_app:doc:{ADR}#ADR 001: Use repositories",
        f"layered_app:doc:{ADR}#Decision",
        "layered_app:doc:docs/guide.md#Developer Guide",
        "layered_app:doc:docs/guide.md#Orders",
    ]
    assert result.nodes[4] == DocNode(
        id=f"layered_app:doc:{ADR}#Decision",
        codebase="layered_app",
        path=ADR,
        heading_path="ADR 001: Use repositories > Decision",
        anchor="Decision",
        text="Data access goes through `UserRepository` and `OrderRepository`.",
        start_line=5,
        end_line=7,
        kind="adr",
    )
    assert result.parse_errors == ()


def test_index_docs_passes_on_parse_errors(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_bytes(b"\xff")
    codebase = Codebase(name="tmp", root=tmp_path, packages=("pkg",), docs=("*.md",))
    result = index_docs(codebase, ())
    assert result.nodes == ()
    assert [error.path for error in result.parse_errors] == ["bad.md"]
    assert isinstance(result.parse_errors[0], ParseError)


def test_a_docs_glob_outside_the_root_is_a_config_error() -> None:
    codebase = LAYERED_APP.model_copy(update={"docs": ("../plainrepo/*.md",)})
    with pytest.raises(ConfigError, match="outside the codebase root"):
        load_docs(codebase)


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can read a chmod 0 file"
)
def test_an_unreadable_doc_is_recorded_and_skipped(tmp_path: Path) -> None:
    (tmp_path / "good.md").write_text("# Good\n", encoding="utf-8")
    locked = tmp_path / "locked.md"
    locked.write_text("# Locked\n", encoding="utf-8")
    locked.chmod(0)
    codebase = Codebase(name="tmp", root=tmp_path, packages=("pkg",), docs=("*.md",))
    try:
        files, errors = load_docs(codebase)
    finally:
        locked.chmod(0o644)
    assert [f.path for f in files] == ["good.md"]
    assert [(e.path, e.line) for e in errors] == [("locked.md", None)]
    assert "cannot read" in errors[0].message


def test_the_memex_self_index_labels_its_adrs() -> None:
    memex = load_config(FIXTURES.parents[1] / "memex.toml").get("memex")
    kinds = {f.path: f.kind for f in load_docs(memex)[0]}

    assert kinds["DESIGN.md"] == "doc"
    adrs = {path: kind for path, kind in kinds.items() if path.startswith("docs/decisions/")}
    assert adrs  # at least ADR-001
    assert set(adrs.values()) == {"adr"}


@pytest.mark.parametrize("pattern", ["/etc/*.md", ""])
def test_an_absolute_or_empty_docs_glob_is_a_config_error(pattern: str) -> None:
    codebase = LAYERED_APP.model_copy(update={"docs": (pattern,)})
    with pytest.raises(ConfigError, match=re.escape(f"docs glob {pattern!r}")):
        load_docs(codebase)
