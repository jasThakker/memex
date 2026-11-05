"""How graph model objects become Neo4j rows, without a database (DESIGN.md section 7)."""

import pytest

from memex.graph.model import (
    ClassNode,
    CodebaseNode,
    DocNode,
    Edge,
    ExternalNode,
    FunctionNode,
    GraphBatch,
    ModuleNode,
)
from memex.graph.store import edge_properties, label_of, node_properties, validate


def test_each_node_type_has_its_label() -> None:
    assert label_of(CodebaseNode(id="c", codebase="c", name="c", root="/r", indexed_at="t")) == (
        "Codebase"
    )
    assert label_of(ModuleNode(id="c:m", codebase="c", qualname="m", path="m.py")) == "Module"
    assert label_of(ExternalNode(id="c:ext:x", codebase="c", name="x")) == "External"
    doc = DocNode(
        id="c:doc:a.md#a",
        codebase="c",
        path="a.md",
        heading_path="A",
        anchor="a",
        text="t",
        start_line=1,
        end_line=2,
    )
    assert label_of(doc) == "Doc"


def test_node_properties_drop_none_and_turn_tuples_into_lists() -> None:
    node = CodebaseNode(
        id="c", codebase="c", name="c", root="/r", indexed_at="t", extractors=("sqlalchemy",)
    )
    cls = ClassNode(
        id="c:m.A", codebase="c", name="A", qualname="m.A", path="m.py", line=3, end_line=9
    )

    assert node_properties(node) == {
        "id": "c",
        "codebase": "c",
        "name": "c",
        "root": "/r",
        "indexed_at": "t",
        "extractors": ["sqlalchemy"],
        "files": 0,
        "parse_errors": 0,
        "unresolved_calls": 0,
    }
    assert "layer" not in node_properties(cls) and "tablename" not in node_properties(cls)
    assert node_properties(cls)["line"] == 3


def test_edge_properties_keep_only_what_the_kind_uses_and_store_ref_kind_as_kind() -> None:
    references = Edge(
        kind="REFERENCES",
        source="c:a",
        target="c:b",
        ref_kind="foreign_key",
        attr="user_id",
        line=14,
        extractor="sqlalchemy",
    )
    imports = Edge(kind="IMPORTS", source="c:a", target="c:b", names=("X", "Y"), line=1)
    defines = Edge(kind="DEFINES", source="c:a", target="c:b")

    assert edge_properties(references) == {
        "kind": "foreign_key",
        "attr": "user_id",
        "line": 14,
        "extractor": "sqlalchemy",
    }
    assert edge_properties(imports) == {"names": ["X", "Y"], "line": 1}
    assert edge_properties(defines) == {}


def test_validate_rejects_batches_the_store_must_not_write() -> None:
    codebase = CodebaseNode(id="c", codebase="c", name="c", root="/r", indexed_at="t")
    module = ModuleNode(id="c:m", codebase="c", qualname="m", path="m.py")
    function = FunctionNode(
        id="c:m.f",
        codebase="c",
        name="f",
        qualname="m.f",
        path="m.py",
        line=1,
        end_line=2,
        signature="f()",
        is_method=False,
        is_async=False,
    )
    defines = Edge(kind="DEFINES", source=module.id, target=function.id)
    validate(GraphBatch(codebase="c", nodes=(codebase, module, function), edges=(defines,)))

    def rejected(nodes: tuple, edges: tuple = ()) -> str:
        with pytest.raises(ValueError) as raised:
            validate(GraphBatch(codebase="c", nodes=nodes, edges=edges))
        return str(raised.value)

    assert "dangling" in rejected((codebase, module), (defines,))
    assert "duplicate" in rejected((codebase, module, module))
    other = ModuleNode(id="d:m", codebase="d", qualname="m", path="m.py")
    assert "another codebase" in rejected((codebase, module, other))
    # Right codebase property, but an id from another codebase's space.
    misplaced = ModuleNode(id="d:x", codebase="c", qualname="x", path="x.py")
    assert "id prefix" in rejected((codebase, misplaced))
    assert "one Codebase node" in rejected((module,))
    wrong = CodebaseNode(id="d", codebase="c", name="d", root="/r", indexed_at="t")
    assert "one Codebase node" in rejected((wrong, module))
