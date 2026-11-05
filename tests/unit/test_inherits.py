"""INHERITS edges: Class -> Class or External, with the base's 0-based position."""

from parsing import REGISTRY, parse_codebase, parse_files

from memex.graph.model import Edge, ExternalNode, GraphBatch
from memex.ingest.code import index_code
from memex.ingest.code.resolver import SymbolTable, link_inherits


def bases(edges: list[Edge], codebase: str) -> set[tuple[str, str, int | None]]:
    """(class, base, position) for each INHERITS edge, without the codebase prefix."""
    prefix = f"{codebase}:"
    return {
        (edge.source.removeprefix(prefix), edge.target.removeprefix(prefix), edge.position)
        for edge in edges
    }


def inherits(codebase: str) -> tuple[list[Edge], list[ExternalNode]]:
    return link_inherits(codebase, SymbolTable(parse_codebase(codebase)))


def test_layered_app_bases_resolve_through_imports_and_reexports() -> None:
    edges, _ = inherits("layered_app")

    assert all(edge.kind == "INHERITS" for edge in edges)
    assert bases(edges, "layered_app") == {
        ("app.db.models.orders.Order", "app.db.models._model_base.SqlAlchemyBase", 0),
        ("app.db.models.users.User", "app.db.models._model_base.SqlAlchemyBase", 0),
        ("app.db.models._model_base.SqlAlchemyBase", "ext:sqlalchemy.orm.DeclarativeBase", 0),
        ("app.schema.order.OrderOut", "ext:pydantic.BaseModel", 0),
        ("app.schema.user.UserOut", "ext:pydantic.BaseModel", 0),
        # direct import of app._base.service
        (
            "app.services.order_services.order_service.OrderService",
            "app._base.service.BaseService",
            0,
        ),
        # through the re-export in app/_base/__init__.py
        ("app.services.user_services.user_service.UserService", "app._base.service.BaseService", 0),
    }


def test_plainrepo_bases_include_an_external_abc() -> None:
    edges, externals = inherits("plainrepo")

    assert bases(edges, "plainrepo") == {
        ("toolkit._transport.base.Transport", "ext:abc.ABC", 0),
        ("toolkit._transport.http.HttpTransport", "toolkit._transport.base.Transport", 0),
    }
    assert externals == [
        ExternalNode(id="plainrepo:ext:abc.ABC", codebase="plainrepo", name="abc.ABC")
    ]


def test_base_forms_positions_and_skipped_bases() -> None:
    modules = parse_files(
        {
            "pkg/__init__.py": "",
            "pkg/base.py": "class Base: ...\nclass Mixin: ...\n",
            "pkg/use.py": """
                import typing
                from typing import Generic, TypeVar
                from pkg import base
                from pkg.base import Base

                T = TypeVar("T")

                class Local: ...

                class A(Base, base.Mixin, Generic[T], metaclass=type): ...
                class B(Local, Exception, object): ...
                class C(typing.Protocol): ...
                class D(make_base()): ...
                class E(A):
                    class Inner(Local): ...
            """,
        }
    )

    edges, externals = link_inherits("lib", SymbolTable(modules))

    assert bases(edges, "lib") == {
        ("pkg.use.A", "pkg.base.Base", 0),
        ("pkg.use.A", "pkg.base.Mixin", 1),  # module alias: base.Mixin
        ("pkg.use.A", "ext:typing.Generic", 2),  # subscript uses its value; metaclass ignored
        ("pkg.use.B", "pkg.use.Local", 0),
        ("pkg.use.B", "ext:builtins.Exception", 1),  # object is skipped
        ("pkg.use.C", "ext:typing.Protocol", 0),  # external module alias
        ("pkg.use.E", "pkg.use.A", 0),
        ("pkg.use.E.Inner", "pkg.use.Local", 0),  # nested class
        # D: a call expression as a base gets no edge
    }
    assert {node.name for node in externals} == {
        "typing.Generic",
        "builtins.Exception",
        "typing.Protocol",
    }


def test_a_local_class_shadows_an_earlier_import_of_the_same_name() -> None:
    modules = parse_files(
        {
            "pkg/__init__.py": "",
            "pkg/use.py": """
                from abc import ABC

                class ABC: ...

                class Impl(ABC): ...
            """,
        }
    )

    edges, externals = link_inherits("lib", SymbolTable(modules))

    assert bases(edges, "lib") == {("pkg.use.Impl", "pkg.use.ABC", 0)}
    assert externals == []


def test_index_code_merges_inherits_externals_with_import_externals() -> None:
    batch: GraphBatch = index_code(REGISTRY.get("layered_app"))
    ids = [node.id for node in batch.nodes]
    inherits_edges = [edge for edge in batch.edges if edge.kind == "INHERITS"]

    assert len(inherits_edges) == 7
    assert ids.count("layered_app:ext:pydantic.BaseModel") == 1
    assert all(edge.target in ids and edge.source in ids for edge in inherits_edges)
