"""callers and callees (DESIGN.md section 10).

The layered_app call edges are the ones tests/unit/test_calls.py checks against the fixture
source. A small hand-built graph covers what the fixture has no shape for: a diamond and a
cycle. Needs Docker. Run with `uv run pytest -m neo4j`.
"""

from pathlib import Path

import pytest
from neo4j import Driver

from memex.config import load_config
from memex.graph.model import (
    CodebaseNode,
    Edge,
    FunctionNode,
    GraphBatch,
    ModuleNode,
    code_id,
)
from memex.graph.store import ensure_schema, replace_codebase
from memex.ingest.code import index_code
from memex.query.calls import callees, callers
from memex.query.models import CallGraph

pytestmark = pytest.mark.neo4j

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAYERED = index_code(load_config(FIXTURES / "memex.toml").get("layered_app"))

ORDER_SERVICE = "app.services.order_services.order_service.OrderService"
BASE_INIT = "app._base.service.BaseService.__init__"
REPOS_INIT = "app.repos.repository_factory.AllRepositories.__init__"
USER_REPO = "app.repos.repository_users.UserRepository"
GET_ORDER = "app.routes.orders.api.get_order"
GET_USER = "app.routes.users.api.get_user"


def loops_batch() -> GraphBatch:
    """m.a -> m.b, m.a -> m.c, m.b -> m.d, m.c -> m.d (a diamond), m.d -> m.a (a cycle) and
    m.d -> m.d (recursion)."""

    def function(name: str, line: int) -> FunctionNode:
        return FunctionNode(
            id=code_id("loops", f"m.{name}"),
            codebase="loops",
            name=name,
            qualname=f"m.{name}",
            path="m.py",
            line=line,
            end_line=line + 1,
            signature=f"{name}()",
            is_method=False,
            is_async=False,
        )

    names = ["a", "b", "c", "d"]
    calls = [
        ("a", "b", 2),
        ("a", "c", 3),
        ("b", "d", 5),
        ("c", "d", 7),
        ("d", "a", 9),
        ("d", "d", 10),
    ]
    return GraphBatch(
        codebase="loops",
        nodes=(
            CodebaseNode(id="loops", codebase="loops", name="loops", root="/x", indexed_at="2026"),
            ModuleNode(id=code_id("loops", "m"), codebase="loops", qualname="m", path="m.py"),
            *(function(name, 1 + 2 * i) for i, name in enumerate(names)),
        ),
        edges=(
            *(
                Edge(
                    kind="DEFINES", source=code_id("loops", "m"), target=code_id("loops", f"m.{n}")
                )
                for n in names
            ),
            *(
                Edge(
                    kind="CALLS",
                    source=code_id("loops", f"m.{a}"),
                    target=code_id("loops", f"m.{b}"),
                    line=line,
                    confidence="exact",
                )
                for a, b, line in calls
            ),
        ),
    )


@pytest.fixture
def indexed(driver: Driver) -> Driver:
    ensure_schema(driver)
    replace_codebase(driver, LAYERED)
    replace_codebase(driver, loops_batch())
    return driver


def hops(graph: CallGraph) -> list[tuple[str, str, str, int]]:
    """(function, via, confidence, distance) per hop, in result order."""
    return [(h.function.qualname, h.via, h.confidence, h.distance) for h in graph.calls]


def edge_line(source: str, target: str) -> int | None:
    return next(
        e.line
        for e in LAYERED.edges
        if e.kind == "CALLS"
        and e.source == code_id("layered_app", source)
        and e.target == code_id("layered_app", target)
    )


def test_callers_at_depth_one(indexed: Driver) -> None:
    graph = callers(indexed, "layered_app", REPOS_INIT)

    assert graph.codebase == "layered_app"
    assert graph.direction == "callers"
    assert graph.depth == 1
    assert graph.symbol is not None and graph.symbol.qualname == REPOS_INIT
    assert hops(graph) == [
        (GET_ORDER, REPOS_INIT, "exact", 1),
        (GET_USER, REPOS_INIT, "exact", 1),
        (f"{ORDER_SERVICE}.default_repos", REPOS_INIT, "exact", 1),
    ]
    assert graph.calls[0].line == edge_line(GET_ORDER, REPOS_INIT)
    assert graph.calls[0].function.layer == "routes"
    assert graph.truncated is False


def test_callers_at_depth_two_name_the_hop_they_came_through(indexed: Driver) -> None:
    graph = callers(indexed, "layered_app", BASE_INIT, depth=2)

    assert hops(graph) == [
        (GET_USER, BASE_INIT, "exact", 1),
        (f"{ORDER_SERVICE}.__init__", BASE_INIT, "exact", 1),
        (GET_ORDER, f"{ORDER_SERVICE}.__init__", "exact", 2),
        (f"{ORDER_SERVICE}.create", f"{ORDER_SERVICE}.__init__", "exact", 2),
    ]
    assert graph.calls[2].line == edge_line(GET_ORDER, f"{ORDER_SERVICE}.__init__")


def test_callees_keep_the_confidence_of_each_edge(indexed: Driver) -> None:
    graph = callees(indexed, "layered_app", f"{ORDER_SERVICE}.owner_name", depth=2)

    assert graph.direction == "callees"
    assert hops(graph) == [
        (f"{USER_REPO}.get_name", f"{ORDER_SERVICE}.owner_name", "inferred", 1),
        (f"{ORDER_SERVICE}.get", f"{ORDER_SERVICE}.owner_name", "exact", 1),
        (
            "app.repos.repository_orders.OrderRepository.get_one",
            f"{ORDER_SERVICE}.get",
            "exact",
            2,
        ),
        (f"{USER_REPO}.get_one", f"{USER_REPO}.get_name", "exact", 2),
    ]


def test_each_function_appears_once_at_its_shortest_distance(indexed: Driver) -> None:
    # d is reached through b and c at distance 2; the cycle back to a is not followed.
    graph = callees(indexed, "loops", "m.a", depth=5)

    assert hops(graph) == [
        ("m.b", "m.a", "exact", 1),
        ("m.c", "m.a", "exact", 1),
        ("m.d", "m.b", "exact", 2),  # ties go to the first `via` by qualname
    ]
    assert graph.calls[2].line == 5


def test_callers_follow_a_cycle_without_repeating(indexed: Driver) -> None:
    graph = callers(indexed, "loops", "m.d", depth=5)

    assert hops(graph) == [
        ("m.b", "m.d", "exact", 1),
        ("m.c", "m.d", "exact", 1),
        ("m.d", "m.d", "exact", 1),  # d calls itself
        ("m.a", "m.b", "exact", 2),
    ]


def test_a_recursive_function_is_its_own_caller_and_callee(indexed: Driver) -> None:
    graph = callees(indexed, "loops", "m.d")

    assert hops(graph) == [("m.a", "m.d", "exact", 1), ("m.d", "m.d", "exact", 1)]
    assert graph.calls[1].line == 10


def test_the_walk_ends_when_nothing_new_is_reached(indexed: Driver) -> None:
    shallow = callees(indexed, "layered_app", f"{ORDER_SERVICE}.owner_name", depth=2)
    deep = callees(indexed, "layered_app", f"{ORDER_SERVICE}.owner_name", depth=5)

    assert deep.calls == shallow.calls
    assert deep.truncated is False


def test_a_class_stands_for_its_own_init(indexed: Driver) -> None:
    graph = callers(indexed, "layered_app", "OrderService")

    assert graph.symbol is not None
    assert graph.symbol.qualname == ORDER_SERVICE
    assert graph.symbol.kind == "class"
    assert hops(graph) == [
        (GET_ORDER, f"{ORDER_SERVICE}.__init__", "exact", 1),
        (f"{ORDER_SERVICE}.create", f"{ORDER_SERVICE}.__init__", "exact", 1),
    ]


def test_a_class_without_its_own_init_and_a_module_have_no_calls(indexed: Driver) -> None:
    # UserService inherits __init__. Calls to UserService() are stored on BaseService.__init__,
    # so they cannot be told apart from other subclasses' constructions: no calls, documented
    # in the tool description and DESIGN.md section 10 (reviewer run 1, finding 3).
    user_service = callers(indexed, "layered_app", "UserService")
    module = callees(indexed, "layered_app", "app.main")

    assert user_service.symbol is not None and user_service.calls == []
    assert module.symbol is not None and module.symbol.kind == "module"
    assert module.calls == []


def test_an_ambiguous_symbol_returns_candidates_and_no_calls(indexed: Driver) -> None:
    graph = callers(indexed, "layered_app", "get")

    assert graph.symbol is None
    assert [c.qualname for c in graph.candidates] == [
        f"{ORDER_SERVICE}.get",
        "app.services.user_services.user_service.UserService.get",
    ]
    assert graph.calls == []
    assert graph.truncated is False


def test_candidates_are_cut_at_the_limit(indexed: Driver) -> None:
    graph = callers(indexed, "layered_app", "get", limit=1)

    assert [c.qualname for c in graph.candidates] == [f"{ORDER_SERVICE}.get"]
    assert graph.truncated is True


def test_an_unknown_symbol_returns_nothing(indexed: Driver) -> None:
    graph = callees(indexed, "layered_app", "Nope")

    assert graph.symbol is None
    assert graph.candidates == []
    assert graph.calls == []


def test_calls_are_truncated_at_the_limit(indexed: Driver) -> None:
    graph = callers(indexed, "layered_app", REPOS_INIT, depth=2, limit=2)

    assert [h[0] for h in hops(graph)] == [GET_ORDER, GET_USER]
    assert graph.truncated is True


def test_truncation_can_happen_at_a_deeper_level(indexed: Driver) -> None:
    # Level 1 is b and c, exactly the limit; d at level 2 is cut.
    cut = callees(indexed, "loops", "m.a", depth=2, limit=2)
    fits = callees(indexed, "loops", "m.a", depth=2, limit=3)

    assert [h[0] for h in hops(cut)] == ["m.b", "m.c"]
    assert cut.truncated is True
    assert [h[0] for h in hops(fits)] == ["m.b", "m.c", "m.d"]
    assert fits.truncated is False


@pytest.mark.parametrize(("depth", "limit"), [(0, 12), (6, 12), (1, 0), (1, 201)])
def test_bad_depth_or_limit_is_an_error(indexed: Driver, depth: int, limit: int) -> None:
    with pytest.raises(ValueError):
        callers(indexed, "layered_app", REPOS_INIT, depth=depth, limit=limit)
