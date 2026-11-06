"""impact_of (DESIGN.md section 10): what depends on a symbol.

Expected dependents are worked out by hand from the layered_app edges that the Phase 2 and 3
fixture tests check (IMPORTS, INHERITS, REFERENCES, CALLS). Doc sections and their MENTIONS
edges are added by hand, so this does not depend on the docs ingest. Needs Docker. Run with
`uv run pytest -m neo4j`.
"""

from dataclasses import replace
from pathlib import Path

import pytest
from neo4j import Driver

from memex.config import load_config
from memex.graph.model import DocNode, Edge, GraphBatch, code_id, doc_id
from memex.graph.store import ensure_schema, replace_codebase
from memex.ingest.code import index_code
from memex.query.impact import impact_of
from memex.query.models import Impact, PathStep

pytestmark = pytest.mark.neo4j

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAYERED = index_code(load_config(FIXTURES / "memex.toml").get("layered_app"))

BASE = "app._base.service.BaseService"
ORDER_SERVICE = "app.services.order_services.order_service.OrderService"
USER_SERVICE = "app.services.user_services.user_service.UserService"
ORDER_MODULE = "app.services.order_services.order_service"
USER_MODULE = "app.services.user_services.user_service"

# (doc path, start line, qualnames it mentions)
DOCS = [
    ("docs/a_init.md", 1, [f"{BASE}.__init__"]),  # mentions a member of the start set
    ("docs/mixed.md", 1, [BASE, "app.db.models.orders.Order"]),  # the symbol and an unrelated
    ("docs/services.md", 1, [BASE]),  # mentions the starting symbol
    ("docs/routes.md", 1, ["app.routes.orders.api.get_order"]),  # mentions a dependent
    ("docs/models.md", 1, ["app.db.models.orders.Order"]),  # unrelated to BaseService
    *((f"docs/extra{i}.md", 1, [ORDER_SERVICE]) for i in range(5)),  # past the cap of 5
]


def with_docs() -> GraphBatch:
    nodes, edges = [], []
    for path, line, mentioned in DOCS:
        node_id = doc_id("layered_app", path, "intro")
        nodes.append(
            DocNode(
                id=node_id,
                codebase="layered_app",
                path=path,
                heading_path="Intro",
                anchor="intro",
                text="Some text.",
                start_line=line,
                end_line=line + 3,
            )
        )
        edges.extend(
            Edge(
                kind="MENTIONS",
                source=node_id,
                target=code_id("layered_app", q),
                match="qualname",
            )
            for q in mentioned
        )
    return replace(LAYERED, nodes=LAYERED.nodes + tuple(nodes), edges=LAYERED.edges + tuple(edges))


@pytest.fixture
def indexed(driver: Driver) -> Driver:
    ensure_schema(driver)
    replace_codebase(driver, with_docs())
    return driver


def groups(impact: Impact) -> list[tuple[str | None, list[tuple[str, int]]]]:
    """(layer, [(qualname, distance), ...]) per group, in result order."""
    return [
        (group.layer, [(d.symbol.qualname, d.distance) for d in group.dependents])
        for group in impact.layers
    ]


def path_of(impact: Impact, qualname: str) -> list[PathStep]:
    return next(
        d.path for g in impact.layers for d in g.dependents if d.symbol.qualname == qualname
    )


BASE_GROUPS = [
    ("base", [("app._base", 1)]),
    (
        "routes",
        [
            ("app.routes.users.api.get_user", 1),
            ("app.routes.orders.api", 2),
            ("app.routes.orders.api.get_order", 2),
            ("app.routes.users.api", 2),
        ],
    ),
    (
        "services",
        [
            (ORDER_MODULE, 1),
            (ORDER_SERVICE, 1),
            (f"{ORDER_SERVICE}.__init__", 1),
            (USER_MODULE, 1),
            (USER_SERVICE, 1),
            (f"{ORDER_SERVICE}.create", 2),
            ("app.services.user_services", 2),
        ],
    ),
]


def test_dependents_are_grouped_by_layer_and_ordered_by_distance(indexed: Driver) -> None:
    impact = impact_of(indexed, "layered_app", "BaseService", limit=12)

    assert impact.codebase == "layered_app"
    assert impact.symbol is not None and impact.symbol.qualname == BASE
    assert impact.max_depth == 3
    assert groups(impact) == BASE_GROUPS
    assert impact.total == 12  # all 12 kept at limit 12
    # 9 docs relate (a_init, mixed, services, routes, extra0..4), more than the cap of 5
    assert len(impact.docs) == 5
    assert impact.truncated is True


def test_each_dependent_carries_its_path_back_to_the_start(indexed: Driver) -> None:
    impact = impact_of(indexed, "layered_app", "BaseService", limit=12)

    assert path_of(impact, ORDER_SERVICE) == [PathStep(edge="INHERITS", to=BASE)]
    assert path_of(impact, ORDER_MODULE) == [PathStep(edge="IMPORTS", to=BASE)]
    # a call to a member of the start set
    assert path_of(impact, "app.routes.users.api.get_user") == [
        PathStep(edge="CALLS", to=f"{BASE}.__init__")
    ]
    assert path_of(impact, "app.routes.orders.api.get_order") == [
        PathStep(edge="CALLS", to=f"{ORDER_SERVICE}.__init__"),
        PathStep(edge="CALLS", to=f"{BASE}.__init__"),
    ]
    assert path_of(impact, "app.routes.orders.api") == [
        PathStep(edge="IMPORTS", to=ORDER_SERVICE),
        PathStep(edge="INHERITS", to=BASE),
    ]


def test_modules_are_leaves(indexed: Driver) -> None:
    # app.routes.orders imports app.routes.orders.api, and app.main imports app.routes.orders;
    # neither depends on BaseService.
    impact = impact_of(indexed, "layered_app", "BaseService", max_depth=5)

    found = {d.symbol.qualname for g in impact.layers for d in g.dependents}
    assert "app.routes.orders" not in found
    assert "app.main" not in found
    assert impact.total == 12


def test_max_depth_limits_the_distance(indexed: Driver) -> None:
    impact = impact_of(indexed, "layered_app", "BaseService", max_depth=1)

    assert impact.max_depth == 1
    assert impact.total == 7
    assert {d.distance for g in impact.layers for d in g.dependents} == {1}


def test_a_module_starts_from_everything_it_defines(indexed: Driver) -> None:
    # Start set: the module, UserRepository, get_one, get_name. get_name -> get_one stays
    # inside the start set and is not a dependent.
    impact = impact_of(indexed, "layered_app", "app.repos.repository_users")

    factory_init = "app.repos.repository_factory.AllRepositories.__init__"
    assert groups(impact) == [
        ("repos", [("app.repos.repository_factory", 1), (factory_init, 1)]),
        ("routes", [("app.routes.orders.api.get_order", 2), ("app.routes.users.api.get_user", 2)]),
        (
            "services",
            [
                (f"{ORDER_SERVICE}.owner_name", 1),
                (f"{USER_SERVICE}.get", 1),
                (f"{ORDER_SERVICE}.default_repos", 2),
                (f"{ORDER_SERVICE}.create", 3),
            ],
        ),
    ]
    assert path_of(impact, f"{ORDER_SERVICE}.owner_name") == [
        PathStep(edge="CALLS", to="app.repos.repository_users.UserRepository.get_name")
    ]
    # through self.repos.users, typed by annotations in the classes themselves
    assert path_of(impact, f"{USER_SERVICE}.get") == [
        PathStep(edge="CALLS", to="app.repos.repository_users.UserRepository.get_one")
    ]
    # AllRepositories.__init__ constructs UserRepository, which has no __init__: USES
    assert path_of(impact, f"{ORDER_SERVICE}.create") == [
        PathStep(edge="CALLS", to=f"{ORDER_SERVICE}.default_repos"),
        PathStep(edge="CALLS", to=factory_init),
        PathStep(edge="USES", to="app.repos.repository_users.UserRepository"),
    ]


def test_references_are_followed_one_step(indexed: Driver) -> None:
    impact = impact_of(indexed, "layered_app", "app.db.models.users.User", limit=12)

    # Order references User, so Order is a dependent; but what depends on Order (users.py
    # imports it under TYPE_CHECKING, repository_orders imports it) does not depend on User
    # through it, so a class reached by REFERENCES is a leaf, like a module. A function that
    # uses User (constructs it) is expanded like a caller.
    assert groups(impact) == [
        (
            "db_models",
            [
                ("app.db.models", 1),
                ("app.db.models.orders", 1),
                ("app.db.models.orders.Order", 1),
            ],
        ),
        (
            "repos",
            [
                ("app.repos.repository_users", 1),
                ("app.repos.repository_users.UserRepository.get_one", 1),
                ("app.repos.repository_users.UserRepository.get_name", 2),
            ],
        ),
        ("routes", [("app.routes.users.api.get_user", 3)]),
        ("services", [(f"{USER_SERVICE}.get", 2), (f"{ORDER_SERVICE}.owner_name", 3)]),
    ]
    assert path_of(impact, "app.db.models.orders.Order") == [
        PathStep(edge="REFERENCES", to="app.db.models.users.User")
    ]
    assert path_of(impact, "app.repos.repository_users.UserRepository.get_one") == [
        PathStep(edge="USES", to="app.db.models.users.User")
    ]


def test_docs_mentioning_the_symbol_or_a_dependent_are_listed(indexed: Driver) -> None:
    impact = impact_of(indexed, "layered_app", "BaseService", max_depth=1)

    # max_depth 1: get_order (distance 2) is not a dependent, so routes.md is left out;
    # models.md mentions nothing related. Docs on the symbol itself come first, then docs on
    # its members, then by the distance of the closest dependent they mention; then by path.
    paths = [doc.path for doc in impact.docs]
    assert paths == [
        "docs/mixed.md",
        "docs/services.md",
        "docs/a_init.md",
        "docs/extra0.md",
        "docs/extra1.md",
    ]
    services = next(doc for doc in impact.docs if doc.path == "docs/services.md")
    assert services.heading_path == "Intro"
    assert (services.start_line, services.end_line) == (1, 4)
    assert services.mentions == [BASE]
    assert impact.truncated is True  # extra2.md to extra4.md are past the cap of 5


def test_doc_mentions_list_only_the_symbol_and_its_dependents(indexed: Driver) -> None:
    impact = impact_of(indexed, "layered_app", "BaseService", max_depth=1)

    mixed = next(doc for doc in impact.docs if doc.path == "docs/mixed.md")
    assert mixed.mentions == [BASE]  # Order is mentioned too, but does not depend on it


def test_docs_reach_dependents_further_away(indexed: Driver) -> None:
    impact = impact_of(indexed, "layered_app", "OrderService.__init__")

    # get_order calls OrderService.__init__; extra0..4 mention OrderService, not a dependent
    assert [doc.path for doc in impact.docs] == ["docs/routes.md"]
    assert impact.truncated is False


def test_dependents_are_truncated_after_the_closest(indexed: Driver) -> None:
    impact = impact_of(indexed, "layered_app", "BaseService", max_depth=1, limit=3)

    assert impact.total == 7
    assert impact.truncated is True
    # the 3 kept are the first by (distance, qualname)
    assert sorted(d.symbol.qualname for g in impact.layers for d in g.dependents) == [
        "app._base",
        "app.routes.users.api.get_user",
        ORDER_MODULE,
    ]


def test_a_limit_equal_to_the_total_does_not_truncate(indexed: Driver) -> None:
    exact = impact_of(indexed, "layered_app", "app.db.models.users.User", limit=9)
    cut = impact_of(indexed, "layered_app", "app.db.models.users.User", limit=8)

    assert (exact.total, exact.truncated) == (9, False)
    assert (cut.total, cut.truncated) == (9, True)


def test_an_ambiguous_symbol_returns_candidates_only(indexed: Driver) -> None:
    impact = impact_of(indexed, "layered_app", "get_one")

    assert impact.symbol is None
    assert len(impact.candidates) == 2
    assert impact.layers == []
    assert impact.docs == []
    assert impact.total == 0


def test_an_unknown_symbol_returns_nothing(indexed: Driver) -> None:
    impact = impact_of(indexed, "layered_app", "Nope")

    assert (impact.symbol, impact.candidates, impact.layers, impact.total) == (None, [], [], 0)


def test_the_default_limit_keeps_the_closest_eight(indexed: Driver) -> None:
    impact = impact_of(indexed, "layered_app", "BaseService")

    kept = [(d.symbol.qualname, d.distance) for g in impact.layers for d in g.dependents]
    assert len(kept) == 8
    assert impact.total == 12
    assert impact.truncated is True


@pytest.mark.parametrize(("max_depth", "limit"), [(0, 12), (6, 12), (3, 0), (3, 201)])
def test_bad_depth_or_limit_is_an_error(indexed: Driver, max_depth: int, limit: int) -> None:
    with pytest.raises(ValueError):
        impact_of(indexed, "layered_app", "BaseService", max_depth=max_depth, limit=limit)
