"""resolve_symbol (the symbol rule) and find_symbol (DESIGN.md section 10).

Expected answers are read from tests/fixtures/layered_app by hand. Needs Docker. Run with
`uv run pytest -m neo4j`.
"""

from pathlib import Path

import pytest
from neo4j import Driver

from memex.config import load_config
from memex.graph.model import (
    ClassNode,
    CodebaseNode,
    Edge,
    FunctionNode,
    GraphBatch,
    ModuleNode,
    code_id,
)
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


def shadow_batch() -> GraphBatch:
    """Shapes the fixture lacks: module `pkg` and module `lib.pkg` (an exact qualname that is
    also the suffix of another), and module `lib.widget` next to class `pkg.widget` (one short
    name, two kinds)."""
    modules = ["pkg", "lib", "lib.pkg", "lib.widget"]
    return GraphBatch(
        codebase="shadow",
        nodes=(
            CodebaseNode(
                id="shadow", codebase="shadow", name="shadow", root="/x", indexed_at="2026"
            ),
            *(
                ModuleNode(
                    id=code_id("shadow", m),
                    codebase="shadow",
                    qualname=m,
                    path=m.replace(".", "/") + ".py",
                )
                for m in modules
            ),
            ClassNode(
                id=code_id("shadow", "pkg.widget"),
                codebase="shadow",
                name="widget",
                qualname="pkg.widget",
                path="pkg.py",
                line=3,
                end_line=4,
            ),
        ),
        edges=(
            Edge(
                kind="DEFINES",
                source=code_id("shadow", "pkg"),
                target=code_id("shadow", "pkg.widget"),
            ),
        ),
    )


@pytest.fixture
def indexed(driver: Driver) -> Driver:
    ensure_schema(driver)
    replace_codebase(driver, LAYERED)
    replace_codebase(driver, PLAIN)
    replace_codebase(driver, shadow_batch())
    return driver


def qualnames(refs: list[SymbolRef]) -> list[str]:
    return [ref.qualname for ref in refs]


# resolve_symbol


def test_a_full_qualname_resolves_to_that_symbol(indexed: Driver) -> None:
    symbol, candidates, truncated = resolve_symbol(indexed, "layered_app", USER_REPO.qualname)

    assert symbol == USER_REPO
    assert candidates == []
    assert truncated is False


def test_an_exact_qualname_wins_over_qualnames_ending_with_it(indexed: Driver) -> None:
    # `pkg` is a module, and also the last segment of module `lib.pkg`.
    symbol, candidates, _ = resolve_symbol(indexed, "shadow", "pkg")

    assert symbol is not None and symbol.qualname == "pkg"
    assert candidates == []


def test_an_exact_qualname_wins_even_past_the_candidate_limit(indexed: Driver) -> None:
    # Sorted by qualname, `lib.pkg` would come first and fill a limit of 1.
    symbol, _, _ = resolve_symbol(indexed, "shadow", "pkg", limit=1)

    assert symbol is not None and symbol.qualname == "pkg"


def test_a_unique_short_name_resolves(indexed: Driver) -> None:
    symbol, candidates, _ = resolve_symbol(indexed, "layered_app", "UserRepository")

    assert symbol == USER_REPO
    assert candidates == []


def test_a_partial_qualname_resolves_when_unique(indexed: Driver) -> None:
    symbol, _, _ = resolve_symbol(indexed, "layered_app", "UserRepository.get_one")

    assert symbol is not None
    assert symbol.qualname == USER_GET_ONE
    assert symbol.kind == "function"
    assert symbol.line == 7


def test_a_module_resolves_with_no_line(indexed: Driver) -> None:
    symbol, _, _ = resolve_symbol(indexed, "layered_app", "repository_users")

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
    symbol, candidates, truncated = resolve_symbol(indexed, "layered_app", "get_one")

    assert symbol is None
    assert qualnames(candidates) == [ORDER_GET_ONE, USER_GET_ONE]
    assert truncated is False


def test_candidates_are_cut_at_the_limit(indexed: Driver) -> None:
    symbol, candidates, truncated = resolve_symbol(indexed, "layered_app", "get_one", limit=1)

    assert symbol is None
    assert qualnames(candidates) == [ORDER_GET_ONE]
    assert truncated is True


def test_two_modules_can_share_a_short_name(indexed: Driver) -> None:
    # `orders` is both the ORM module and the routes package.
    symbol, candidates, _ = resolve_symbol(indexed, "layered_app", "orders")

    assert symbol is None
    assert qualnames(candidates) == ["app.db.models.orders", "app.routes.orders"]


def test_candidates_can_be_of_different_kinds(indexed: Driver) -> None:
    symbol, candidates, _ = resolve_symbol(indexed, "shadow", "widget")

    assert symbol is None
    assert [(ref.qualname, ref.kind) for ref in candidates] == [
        ("lib.widget", "module"),
        ("pkg.widget", "class"),
    ]


def test_a_short_name_matches_whole_segments_only(indexed: Driver) -> None:
    # "Repository" is a substring of UserRepository, not a name segment.
    assert resolve_symbol(indexed, "layered_app", "Repository") == (None, [], False)


def test_an_unknown_name_returns_nothing(indexed: Driver) -> None:
    assert resolve_symbol(indexed, "layered_app", "Nope") == (None, [], False)


def test_resolution_stays_inside_the_named_codebase(indexed: Driver) -> None:
    assert resolve_symbol(indexed, "plainrepo", "UserRepository") == (None, [], False)


def test_surrounding_whitespace_is_ignored(indexed: Driver) -> None:
    symbol, _, _ = resolve_symbol(indexed, "layered_app", "  UserRepository ")

    assert symbol == USER_REPO


@pytest.mark.parametrize(("symbol", "limit"), [("", 10), ("  ", 10), ("get", 0), ("get", 201)])
def test_resolve_symbol_rejects_bad_arguments(indexed: Driver, symbol: str, limit: int) -> None:
    with pytest.raises(ValueError):
        resolve_symbol(indexed, "layered_app", symbol, limit=limit)


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


def test_find_symbol_puts_an_exact_qualname_first(indexed: Driver) -> None:
    by_qualname = find_symbol(indexed, "layered_app", USER_REPO.qualname)
    shadowed = find_symbol(indexed, "shadow", "pkg")

    assert [s.qualname for s in by_qualname.symbols] == [USER_REPO.qualname]
    assert [s.qualname for s in shadowed.symbols] == ["pkg", "lib.pkg"]


def test_find_symbol_truncates_at_the_limit_keeping_the_best(indexed: Driver) -> None:
    full = find_symbol(indexed, "layered_app", "get", kind="function")
    cut = find_symbol(indexed, "layered_app", "get", kind="function", limit=3)
    exact = find_symbol(indexed, "layered_app", "get", kind="function", limit=7)

    assert len(full.symbols) == 7
    assert cut.symbols == full.symbols[:3]
    assert cut.truncated is True
    assert exact.symbols == full.symbols
    assert exact.truncated is False


def test_find_symbol_stays_inside_the_named_codebase(indexed: Driver) -> None:
    assert find_symbol(indexed, "plainrepo", "UserRepository").symbols == []


def test_find_symbol_with_no_match_is_empty(indexed: Driver) -> None:
    result = find_symbol(indexed, "layered_app", "Nope")

    assert result.symbols == []
    assert result.truncated is False


@pytest.mark.parametrize(("name", "limit"), [("get", 0), ("get", 201), ("", 10), ("  ", 10)])
def test_find_symbol_rejects_bad_arguments(indexed: Driver, name: str, limit: int) -> None:
    with pytest.raises(ValueError):
        find_symbol(indexed, "layered_app", name, limit=limit)


def test_find_symbol_rejects_an_unknown_kind(indexed: Driver) -> None:
    with pytest.raises(ValueError):
        find_symbol(indexed, "layered_app", "get", kind="method")  # type: ignore[arg-type]
