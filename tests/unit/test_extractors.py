"""Framework extractors: the Extractor Protocol, its registry and the `sqlalchemy` extractor.

Extractors only add edges between nodes that exist, plus a few declared class properties
(`tablename`). They run only when a codebase lists them in `extractors` (DESIGN.md section 6).
"""

from pathlib import Path

import pytest
from parsing import FIXTURES, REGISTRY, parse_codebase, parse_files

from memex.config import ConfigError, load_config
from memex.graph.model import ClassNode, Edge, GraphBatch
from memex.ingest.code import index_code
from memex.ingest.code.extractors import EXTRACTORS
from memex.ingest.code.extractors.sqlalchemy import SqlAlchemyExtractor
from memex.ingest.code.resolver import SymbolTable

REPO_ROOT = FIXTURES.parents[1]


def references(edges: list[Edge] | tuple[Edge, ...], codebase: str) -> set[tuple]:
    """(source, target, kind, attr, line, extractor) per REFERENCES edge, ids unprefixed."""
    prefix = f"{codebase}:"
    return {
        (
            edge.source.removeprefix(prefix),
            edge.target.removeprefix(prefix),
            edge.ref_kind,
            edge.attr,
            edge.line,
            edge.extractor,
        )
        for edge in edges
        if edge.kind == "REFERENCES"
    }


def extract(files: dict[str, str]) -> list[Edge]:
    modules = parse_files(files)
    return SqlAlchemyExtractor().extract(modules, SymbolTable(modules))


ORDER = "app.db.models.orders.Order"
USER = "app.db.models.users.User"


def test_registry_maps_names_to_extractors() -> None:
    assert list(EXTRACTORS.items()) == [("sqlalchemy", SqlAlchemyExtractor)]
    assert SqlAlchemyExtractor.name == "sqlalchemy"


def test_every_extractor_named_in_a_config_is_registered() -> None:
    for config in (REPO_ROOT / "memex.toml", FIXTURES / "memex.toml"):
        for codebase in load_config(config).codebases.values():
            assert set(codebase.extractors) <= set(EXTRACTORS), (config, codebase.name)


def test_sqlalchemy_references_in_layered_app() -> None:
    modules = parse_codebase("layered_app")
    edges = SqlAlchemyExtractor().extract(modules, SymbolTable(modules))

    assert all(edge.kind == "REFERENCES" for edge in edges)
    assert references(edges, "layered_app") == {
        (ORDER, USER, "foreign_key", "user_id", 14, "sqlalchemy"),  # ForeignKey("users.id")
        (ORDER, USER, "relationship", "user", 15, "sqlalchemy"),  # relationship(User)
        (USER, ORDER, "relationship", "orders", 19, "sqlalchemy"),  # relationship("Order")
    }


def test_sqlalchemy_sets_tablename_on_models() -> None:
    modules = parse_codebase("layered_app")
    properties = SqlAlchemyExtractor().class_properties(modules, SymbolTable(modules))

    assert properties == {
        f"layered_app:{ORDER}": {"tablename": "orders"},
        f"layered_app:{USER}": {"tablename": "users"},
    }


def test_index_code_runs_listed_extractors_and_applies_tablename() -> None:
    batch = index_code(REGISTRY.get("layered_app"))
    tablenames = {
        node.qualname: node.tablename for node in batch.nodes if isinstance(node, ClassNode)
    }
    ids = {node.id for node in batch.nodes}

    assert len(references(batch.edges, "layered_app")) == 3
    assert all(edge.source in ids and edge.target in ids for edge in batch.edges)
    assert tablenames[ORDER] == "orders"
    assert tablenames[USER] == "users"
    assert tablenames["app.services.order_services.order_service.OrderService"] is None


def test_no_references_or_tablename_when_the_extractor_is_not_listed() -> None:
    # The same models, with the extractor switched off: the guard that extractors are opt-in.
    codebase = REGISTRY.get("layered_app").model_copy(update={"extractors": ()})
    batch: GraphBatch = index_code(codebase)

    assert [edge for edge in batch.edges if edge.kind == "REFERENCES"] == []
    assert all(node.tablename is None for node in batch.nodes if isinstance(node, ClassNode))


def test_unknown_extractor_name_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    codebase = REGISTRY.get("plainrepo").model_copy(
        update={"root": tmp_path, "packages": ("pkg",), "extractors": ("django",)}
    )

    with pytest.raises(ConfigError, match="unknown extractor 'django'.*sqlalchemy"):
        index_code(codebase)


def test_sqlalchemy_forms_and_cases_that_give_no_edge() -> None:
    edges = extract(
        {
            "pkg/__init__.py": "",
            "pkg/models.py": """
                import sqlalchemy as sa
                from sqlalchemy import Column, ForeignKey
                from sqlalchemy.orm import relationship

                class Team:
                    __tablename__ = "teams"

                class Player:
                    __tablename__ = "players"
                    team_id = Column(sa.Integer, sa.ForeignKey("teams.id"))
                    captain_of = Column(ForeignKey("main.teams.id"))  # schema-qualified
                    team = relationship("pkg.models.Team")  # dotted string
                    coach = relationship("Coach")  # no such class
                    league_id = Column(ForeignKey("leagues.id"))  # no such table
                    clone = relationship("Twin")  # two mapped classes named Twin, neither imported
            """,
            "pkg/more.py": 'class Twin:\n    __tablename__ = "more_twins"\n',
            "pkg/other.py": """
                def relationship(target): ...
                def ForeignKey(target): ...

                class Twin:
                    __tablename__ = "twins"
                    team = relationship("Team")  # not the sqlalchemy function
                    team_id = ForeignKey("teams.id")
            """,
        }
    )

    assert references(edges, "lib") == {
        ("pkg.models.Player", "pkg.models.Team", "foreign_key", "team_id", 11, "sqlalchemy"),
        ("pkg.models.Player", "pkg.models.Team", "foreign_key", "captain_of", 12, "sqlalchemy"),
        ("pkg.models.Player", "pkg.models.Team", "relationship", "team", 13, "sqlalchemy"),
    }


def test_two_classes_with_the_same_tablename_give_no_foreign_key_edge() -> None:
    edges = extract(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": 'class A:\n    __tablename__ = "things"\n',
            "pkg/b.py": 'class B:\n    __tablename__ = "things"\n',
            "pkg/c.py": """
                from sqlalchemy import Column, ForeignKey

                class C:
                    thing_id = Column(ForeignKey("things.id"))
            """,
        }
    )

    assert edges == []


def test_symbol_table_finds_classes_by_class_attribute() -> None:
    symbols = SymbolTable(parse_codebase("layered_app"))

    assert symbols.by_class_attribute("__tablename__", "users") == [USER]
    assert symbols.by_class_attribute("__tablename__", "missing") == []


def pairs(edges: list[Edge]) -> set[tuple[str, str, str | None, str | None]]:
    """(source, target, kind, attr) per edge, without the `lib:` prefix."""
    return {
        (
            edge.source.removeprefix("lib:"),
            edge.target.removeprefix("lib:"),
            edge.ref_kind,
            edge.attr,
        )
        for edge in edges
    }


def test_sqlalchemy_functions_reexported_by_a_codebase_module() -> None:
    edges = extract(
        {
            "pkg/__init__.py": "",
            "pkg/db.py": """
                from sqlalchemy import ForeignKey
                from sqlalchemy.orm import relationship
            """,
            "pkg/models.py": """
                from sqlalchemy import Column
                from pkg.db import ForeignKey, relationship

                class Team:
                    __tablename__ = "teams"

                class Player:
                    __tablename__ = "players"
                    team_id = Column(ForeignKey("teams.id"))
                    team = relationship("Team")
            """,
        }
    )

    assert pairs(edges) == {
        ("pkg.models.Player", "pkg.models.Team", "foreign_key", "team_id"),
        ("pkg.models.Player", "pkg.models.Team", "relationship", "team"),
    }


def test_string_relationships_only_reach_mapped_classes() -> None:
    edges = extract(
        {
            "pkg/__init__.py": "",
            "pkg/schema.py": """
                class User: ...  # an API schema, not a model
                class Tag: ...
            """,
            "pkg/base.py": """
                from sqlalchemy.orm import DeclarativeBase

                class Model(DeclarativeBase): ...
            """,
            "pkg/users.py": """
                from pkg.base import Model

                class User(Model):
                    __tablename__ = "users"

                class Admin(User): ...  # mapped through its base, no tablename of its own
            """,
            "pkg/orders.py": """
                from sqlalchemy.orm import relationship
                from pkg.base import Model
                from pkg.schema import User

                class Order(Model):
                    __tablename__ = "orders"
                    user = relationship("User")  # the mapped User, not the imported schema
                    approver = relationship("Admin")
                    tags = relationship("Tag")  # only a non-model is called Tag
            """,
        }
    )

    assert pairs(edges) == {
        ("pkg.orders.Order", "pkg.users.User", "relationship", "user"),
        ("pkg.orders.Order", "pkg.users.Admin", "relationship", "approver"),
    }


def test_lambda_column_attribute_type_checking_and_self_references() -> None:
    edges = extract(
        {
            "pkg/__init__.py": "",
            "pkg/models.py": """
                from typing import TYPE_CHECKING
                from sqlalchemy import Column, ForeignKey
                from sqlalchemy.orm import relationship

                if TYPE_CHECKING:
                    from pkg.other import Team

                class Node:
                    __tablename__ = "nodes"
                    parent_id = Column(ForeignKey("nodes.id"))  # self-reference
                    team_id = Column(ForeignKey(Team.id))  # ForeignKey(Model.id)
                    team = relationship("Team")  # imported only for type checking
                    peers = relationship(lambda: Node)
            """,
            "pkg/other.py": """
                class Team:
                    __tablename__ = "teams"
            """,
        }
    )

    assert pairs(edges) == {
        ("pkg.models.Node", "pkg.models.Node", "foreign_key", "parent_id"),
        ("pkg.models.Node", "pkg.other.Team", "foreign_key", "team_id"),
        ("pkg.models.Node", "pkg.other.Team", "relationship", "team"),
        ("pkg.models.Node", "pkg.models.Node", "relationship", "peers"),
    }


def test_a_declared_attr_tablename_on_a_base_maps_its_subclasses() -> None:
    edges = extract(
        {
            "pkg/__init__.py": "",
            "pkg/models.py": """
                from sqlalchemy.orm import declared_attr, relationship

                class Base:
                    @declared_attr
                    def __tablename__(cls) -> str:
                        return cls.__name__.lower()

                class User(Base): ...

                class Order(Base):
                    user = relationship("User")
            """,
        }
    )

    assert pairs(edges) == {("pkg.models.Order", "pkg.models.User", "relationship", "user")}
