from pathlib import Path

import pytest

from memex.config import load_config
from memex.graph.model import ClassNode, Edge, FunctionNode
from memex.ingest.code import index_code
from memex.ingest.docs import index_docs
from memex.ingest.docs.mentions import MentionTargets, link_mentions

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGISTRY = load_config(FIXTURES / "memex.toml")
LAYERED_APP = REGISTRY.get("layered_app")
PLAINREPO = REGISTRY.get("plainrepo")
TARGETS = MentionTargets(index_code(LAYERED_APP).nodes)
ADR = "docs/decisions/001-use-repositories.md"


def mentions(codebase_name: str) -> set[tuple[str, str, str]]:
    codebase = REGISTRY.get(codebase_name)
    edges = index_docs(codebase, index_code(codebase).nodes).edges
    assert all(edge.kind == "MENTIONS" for edge in edges)
    assert len({(e.source, e.target) for e in edges}) == len(edges)  # one per target
    prefix = f"{codebase_name}:"
    return {
        (e.source.removeprefix(f"{prefix}doc:"), e.target.removeprefix(prefix), str(e.match))
        for e in edges
    }


def test_layered_app_docs_mention_exactly_the_symbols_they_name() -> None:
    assert mentions("layered_app") == {
        ("AGENTS.md#Agent Guide", "app.main", "path"),
        ("AGENTS.md#Agent Guide", "app.main.create_app", "backtick_name"),  # `create_app()`
        ("AGENTS.md#Layers", "app.routes", "path"),  # a package directory, trailing slash
        ("AGENTS.md#Layers", "app._base.service.BaseService", "backtick_name"),
        ("AGENTS.md#Layers", "app.repos.repository_factory.AllRepositories", "backtick_name"),
        # not linked in Layers: `get_one` (a bare method name), `get` (a builtin type method),
        # `__init__` (dunder), `dict` (a builtin)
        ("AGENTS.md#Database", "app.db.models", "path"),
        ("AGENTS.md#Database", "app.db.models._model_base.SqlAlchemyBase", "qualname"),
        # not linked in Database: app/migrations/ (excluded from the walk),
        # app.db.models.missing.Thing (no such qualname, no prefix fallback),
        # app/repos/repository_*.py (a glob)
        (f"{ADR}#Decision", "app.repos.repository_users.UserRepository", "backtick_name"),
        (f"{ADR}#Decision", "app.repos.repository_orders.OrderRepository", "backtick_name"),
        (
            "docs/guide.md#Orders",
            "app.services.order_services.order_service.OrderService.create",
            "backtick_name",  # dotted span, unique qualname suffix
        ),
        (
            "docs/guide.md#Orders",
            "app.repos.repository_orders.OrderRepository.get_one",
            "backtick_name",  # the dotted form is unique even though `get_one` is not
        ),
        (
            "docs/guide.md#Orders",
            "app.services.order_services.order_service.OrderService",
            "qualname",  # backticked full qualname
        ),
        ("docs/guide.md#Orders", "app.schema.order", "qualname"),  # inside a code fence
    }


def test_plainrepo_readme_mentions_with_defaults_only() -> None:
    assert mentions("plainrepo") == {
        ("README.md#Toolkit", "toolkit._client.Client", "backtick_name"),
        ("README.md#Toolkit", "toolkit.text.slug.slugify", "backtick_name"),
        ("README.md#Toolkit", "toolkit.text.slug", "path"),  # sentence period stripped
    }


def linked(text: str) -> list[tuple[str, str | None]]:
    edges = link_mentions("layered_app:doc:x.md#X", text, TARGETS)
    assert all(isinstance(edge, Edge) and edge.source == "layered_app:doc:x.md#X" for edge in edges)
    return [(edge.target.removeprefix("layered_app:"), edge.match) for edge in edges]


def test_one_edge_per_target_with_the_strongest_match() -> None:
    text = (
        "`AllRepositories` is app.repos.repository_factory.AllRepositories; app/main.py is app.main"
    )
    assert linked(text) == [
        ("app.main", "qualname"),
        ("app.repos.repository_factory.AllRepositories", "qualname"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "see https://example.com/app/main.py",  # a URL is not a repo path
        "routes/users/api.py",  # paths are relative to the codebase root, not the package
        "app/main",  # neither a .py file nor a package directory
        "```\n`AllRepositories`\n```",  # backticks inside a fence are code, not a span
        "AllRepositories without backticks",  # bare words are never matched
        "`create_app(settings)`",  # a call with arguments is not a name
        "`self.repos.orders.get_one()`",  # no qualname ends with this
        "`main`",  # modules are matched by qualname or path only
        "xapp.main and app.mainly",  # part of a longer name
    ],
)
def test_no_false_hits(text: str) -> None:
    assert linked(text) == []


def test_a_bare_method_name_needs_its_class() -> None:
    # `get_name` is unique, but bare method names in real docs are mostly ordinary words
    # (`slug`, `json`, `timeout`); a method links only through its dotted form
    assert linked("`get_name` and `create`") == []
    assert linked("`UserRepository.get_name()`") == [
        ("app.repos.repository_users.UserRepository.get_name", "backtick_name")
    ]


def test_double_backtick_span_and_leading_dot_slash() -> None:
    assert linked("``BaseService`` in ./app/_base/service.py") == [
        ("app._base.service", "path"),
        ("app._base.service.BaseService", "backtick_name"),
    ]


def test_a_top_level_package_directory_is_a_path() -> None:
    assert linked("All code lives in `app/`.") == [("app", "path")]
    assert linked("All code lives in app/.") == [("app", "path")]


def function(qualname: str, is_method: bool = False) -> FunctionNode:
    return FunctionNode(
        id=f"lib:{qualname}",
        codebase="lib",
        name=qualname.rsplit(".", 1)[1],
        qualname=qualname,
        path="lib/x.py",
        line=1,
        end_line=1,
        signature="()",
        is_method=is_method,
        is_async=False,
    )


def klass(qualname: str) -> ClassNode:
    name = qualname.rsplit(".", 1)[1]
    return ClassNode(
        id=f"lib:{qualname}", codebase="lib", name=name, qualname=qualname, path="lib/x.py",
        line=1, end_line=1,
    )  # fmt: skip


# Module-level names that collide with common words, and names shared by two symbols
LIB = MentionTargets(
    [
        function("lib.util.get"),  # a builtin type method name
        klass("lib.util.dict"),  # a builtin
        function("lib.util.match"),  # a soft keyword
        function("lib.util.__getattr__"),  # a dunder
        function("lib.a.run"),
        function("lib.b.run"),  # `run` is ambiguous
        klass("lib.a.Worker"),
        function("lib.a.Worker.start", is_method=True),
        klass("lib.b.Worker"),
        function("lib.b.Worker.start", is_method=True),  # `Worker.start` is ambiguous
        function("lib.util.unique_helper"),
    ]
)


def lib_linked(text: str) -> list[str]:
    return [edge.target.removeprefix("lib:") for edge in link_mentions("lib:doc:x#", text, LIB)]


@pytest.mark.parametrize(
    "span", ["`get`", "`dict`", "`match`", "`__getattr__`", "`run`", "`Worker`", "`Worker.start`"]
)
def test_common_or_ambiguous_names_give_no_edge(span: str) -> None:
    assert lib_linked(span) == []


def test_unique_names_and_suffixes_link() -> None:
    assert lib_linked("`unique_helper()` and `a.Worker.start` and `b.run`") == [
        "lib.a.Worker.start",
        "lib.b.run",
        "lib.util.unique_helper",
    ]
