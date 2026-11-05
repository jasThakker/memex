"""resolve_symbol (the symbol rule) and find_symbol (DESIGN.md section 10).

Expected answers are read from tests/fixtures/layered_app by hand. Needs Docker. Run with
`uv run pytest -m neo4j`.
"""

from pathlib import Path

import pytest
from neo4j import Driver

from memex.config import load_config
from memex.graph.model import FunctionNode
from memex.graph.store import ensure_schema, replace_codebase
from memex.ingest.code import index_code
from memex.query.models import SymbolRef
from memex.query.symbols import find_symbol, resolve_symbol

pytestmark = pytest.mark.neo4j

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGISTRY = load_config(FIXTURES / "memex.toml")
LAYERED = index_code(REGISTRY.get("layered_app"))
PLAIN = index_code(REGISTRY.get("plainrepo"))

USER_REPO = SymbolRef(
    qualname="app.repos.repository_users.UserRepository",
    kind="class",
    path="app/repos/repository_users.py",
    line=6,
    layer="repos",
    domain="user",
)
ORDER_GET_ONE = "app.repos.repository_orders.OrderRepository.get_one"
USER_GET_ONE = "app.repos.repository_users.UserRepository.get_one"


@pytest.fixture
def indexed(driver: Driver) -> Driver:
    ensure_schema(driver)
    replace_codebase(driver, LAYERED)
    replace_codebase(driver, PLAIN)
    return driver


def qualnames(refs: list[SymbolRef]) -> list[str]:
    return [ref.qualname for ref in refs]


# resolve_symbol


def test_a_full_qualname_resolves_to_that_symbol(indexed: Driver) -> None:
    symbol, candidates = resolve_symbol(indexed, "layered_app", USER_REPO.qualname)

    assert symbol == USER_REPO
    assert candidates == []


def test_a_unique_short_name_resolves(indexed: Driver) -> None:
    symbol, candidates = resolve_symbol(indexed, "layered_app", "UserRepository")

    assert symbol == USER_REPO
    assert candidates == []


def test_a_partial_qualname_resolves_when_unique(indexed: Driver) -> None:
    symbol, _ = resolve_symbol(indexed, "layered_app", "UserRepository.get_one")

    assert symbol is not None
    assert symbol.qualname == USER_GET_ONE
    assert symbol.kind == "function"
    assert symbol.line == 7


def test_a_module_resolves_with_no_line(indexed: Driver) -> None:
    symbol, _ = resolve_symbol(indexed, "layered_app", "repository_users")

    assert symbol == SymbolRef(
        qualname="app.repos.repository_users",
        kind="module",
        path="app/repos/repository_users.py",
        line=None,
        layer="repos",
        domain="user",
    )


def test_a_name_shared_by_several_symbols_returns_candidates_and_no_guess(
    indexed: Driver,
) -> None:
    symbol, candidates = resolve_symbol(indexed, "layered_app", "get_one")

    assert symbol is None
    assert qualnames(candidates) == [ORDER_GET_ONE, USER_GET_ONE]


def test_candidates_can_be_of_different_kinds(indexed: Driver) -> None:
    # `orders` is both the ORM module and the routes package.
    symbol, candidates = resolve_symbol(indexed, "layered_app", "orders")

    assert symbol is None
    assert qualnames(candidates) == ["app.db.models.orders", "app.routes.orders"]
    assert {ref.kind for ref in candidates} == {"module"}


def test_a_short_name_matches_whole_segments_only(indexed: Driver) -> None:
    # "Repository" is a substring of UserRepository, not a name segment.
    assert resolve_symbol(indexed, "layered_app", "Repository") == (None, [])


def test_an_unknown_name_returns_nothing(indexed: Driver) -> None:
    assert resolve_symbol(indexed, "layered_app", "Nope") == (None, [])


def test_resolution_stays_inside_the_named_codebase(indexed: Driver) -> None:
    assert resolve_symbol(indexed, "plainrepo", "UserRepository") == (None, [])


# find_symbol


def test_find_symbol_returns_full_symbols_with_signature(indexed: Driver) -> None:
    result = find_symbol(indexed, "layered_app", "UserRepository.get_one")

    node = next(
        n for n in LAYERED.nodes if isinstance(n, FunctionNode) and n.qualname == USER_GET_ONE
    )
    assert result.codebase == "layered_app"
    assert result.query == "UserRepository.get_one"
    assert result.kind == "any"
    assert [s.qualname for s in result.symbols] == [USER_GET_ONE]
    assert result.symbols[0].signature == node.signature
    assert result.truncated is False


def test_find_symbol_ranks_suffix_matches_before_substring_matches(indexed: Driver) -> None:
    result = find_symbol(indexed, "layered_app", "get", kind="function")

    assert [s.qualname for s in result.symbols] == [
        # name is exactly `get`
        "app.services.order_services.order_service.OrderService.get",
        "app.services.user_services.user_service.UserService.get",
        # `get` inside the last name segment, by qualname
        ORDER_GET_ONE,
        "app.repos.repository_users.UserRepository.get_name",
        USER_GET_ONE,
        "app.routes.orders.api.get_order",
        "app.routes.users.api.get_user",
    ]


def test_find_symbol_substring_matching_ignores_case(indexed: Driver) -> None:
    result = find_symbol(indexed, "layered_app", "order", kind="class")

    assert [s.qualname for s in result.symbols] == [
        "app.db.models.orders.Order",
        "app.repos.repository_orders.OrderRepository",
        "app.schema.order.OrderOut",
        "app.services.order_services.order_service.OrderService",
    ]


def test_find_symbol_filters_by_kind(indexed: Driver) -> None:
    result = find_symbol(indexed, "layered_app", "order", kind="module")

    assert [s.qualname for s in result.symbols] == [
        "app.schema.order",  # suffix match
        "app.db.models.orders",
        "app.repos.repository_orders",
        "app.routes.orders",
        "app.services.order_services",
        "app.services.order_services.order_service",
    ]
    assert all(s.kind == "module" and s.signature is None for s in result.symbols)


def test_find_symbol_truncates_at_the_limit(indexed: Driver) -> None:
    result = find_symbol(indexed, "layered_app", "get", kind="function", limit=3)

    assert len(result.symbols) == 3
    assert result.truncated is True


def test_find_symbol_with_no_match_is_empty(indexed: Driver) -> None:
    result = find_symbol(indexed, "layered_app", "Nope")

    assert result.symbols == []
    assert result.truncated is False


@pytest.mark.parametrize(("name", "limit"), [("get", 0), ("get", 201), ("", 10), ("  ", 10)])
def test_find_symbol_rejects_bad_arguments(indexed: Driver, name: str, limit: int) -> None:
    with pytest.raises(ValueError):
        find_symbol(indexed, "layered_app", name, limit=limit)
