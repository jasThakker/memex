from dataclasses import FrozenInstanceError

import pytest

from memex.graph.model import Edge, ModuleNode, code_id, doc_id, external_id


def test_ids_are_scoped_by_codebase() -> None:
    assert code_id("shop", "app.services.UserService") == "shop:app.services.UserService"
    assert external_id("shop", "pydantic.BaseModel") == "shop:ext:pydantic.BaseModel"
    assert doc_id("shop", "docs/guide.md", "database-changes") == (
        "shop:doc:docs/guide.md#database-changes"
    )


def test_labels_are_unset_until_classified() -> None:
    module = ModuleNode(
        id=code_id("shop", "app.main"), codebase="shop", qualname="app.main", path="app/main.py"
    )

    assert module.layer is None
    assert module.domain is None
    assert module.docstring is None


def test_nodes_and_edges_are_frozen() -> None:
    module = ModuleNode(
        id=code_id("shop", "app.main"), codebase="shop", qualname="app.main", path="app/main.py"
    )
    edge = Edge(kind="DEFINES", source=module.id, target=code_id("shop", "app.main.create_app"))

    with pytest.raises(FrozenInstanceError):
        module.layer = "routes"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        edge.line = 3  # type: ignore[misc]
