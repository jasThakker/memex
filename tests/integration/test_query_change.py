"""check_change (DESIGN.md section 10): which code a proposed change affects and which
documented rules apply.

Affected counts are worked out from the impact_of expectations in test_query_impact.py
(BaseService has 12 dependents within depth 3; app.repos.repository_users has 2 others).
Needs Docker. Run with `uv run pytest -m neo4j`.
"""

from pathlib import Path

import pytest
from neo4j import Driver

from memex.config import load_config
from memex.graph.store import ensure_schema, replace_codebase
from memex.ingest.code import index_code
from memex.query import change
from memex.query.change import check_change
from memex.query.models import ChangeCheck, ChangeProposal, LayerCount

pytestmark = pytest.mark.neo4j

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAYERED = index_code(load_config(FIXTURES / "memex.toml").get("layered_app"))

BASE = "app._base.service.BaseService"
USER_REPOS = "app.repos.repository_users"

BASE_AFFECTED = [
    LayerCount(layer="base", count=1),
    LayerCount(layer="routes", count=4),
    LayerCount(layer="services", count=7),
]


@pytest.fixture
def indexed(driver: Driver) -> Driver:
    ensure_schema(driver)
    replace_codebase(driver, LAYERED)
    return driver


def check(driver: Driver, description: str, symbols: list[str] | None = None) -> ChangeCheck:
    proposal = ChangeProposal(description=description, symbols=symbols or [])
    return check_change(driver, "layered_app", proposal)


def resolved(result: ChangeCheck) -> list[str]:
    return [ref.qualname for ref in result.resolved_symbols]


def test_explicit_symbols_are_resolved_and_their_dependents_counted_by_layer(
    indexed: Driver,
) -> None:
    result = check(indexed, "Rename the base class.", ["BaseService"])

    assert result.codebase == "layered_app"
    assert resolved(result) == [BASE]
    assert result.ambiguous == []
    assert result.unresolved == []
    assert result.affected.total == 12
    assert result.affected.layers == BASE_AFFECTED
    assert result.truncated is False


def test_explicit_symbols_win_over_names_in_the_description(indexed: Driver) -> None:
    result = check(indexed, "Change `BaseService` too.", ["UserRepository"])

    assert resolved(result) == [f"{USER_REPOS}.UserRepository"]


def test_without_symbols_code_names_in_the_description_are_resolved(indexed: Driver) -> None:
    result = check(indexed, f"Change `BaseService` and split {USER_REPOS} in two.")

    assert resolved(result) == [BASE, USER_REPOS]
    # one walk from both start sets: repository_factory and OrderService.owner_name join
    assert result.affected.total == 14
    assert result.affected.layers == [
        LayerCount(layer="base", count=1),
        LayerCount(layer="repos", count=1),
        LayerCount(layer="routes", count=4),
        LayerCount(layer="services", count=8),
    ]


def test_a_symbol_named_twice_is_resolved_once(indexed: Driver) -> None:
    result = check(indexed, "Rename it.", ["BaseService", BASE])

    assert resolved(result) == [BASE]
    assert result.affected.total == 12


def test_a_shared_short_name_is_ambiguous_never_guessed(indexed: Driver) -> None:
    result = check(indexed, "Make `get_one` cache its rows.")

    assert result.resolved_symbols == []
    assert [a.name for a in result.ambiguous] == ["get_one"]
    assert [c.qualname for c in result.ambiguous[0].candidates] == [
        "app.repos.repository_orders.OrderRepository.get_one",
        f"{USER_REPOS}.UserRepository.get_one",
    ]
    assert result.affected.total == 0
    assert result.affected.layers == []


def test_names_that_match_nothing_are_unresolved(indexed: Driver) -> None:
    result = check(indexed, "Rename `base_url` and NoSuchThing; keep the rest.")

    assert result.resolved_symbols == []
    assert result.unresolved == ["base_url", "NoSuchThing"]
    assert result.affected.total == 0


def test_plain_words_are_neither_resolved_nor_unresolved(indexed: Driver) -> None:
    result = check(indexed, "Make the services faster.")

    assert result.resolved_symbols == []
    assert result.unresolved == []


def test_at_most_max_tokens_names_are_read_from_the_description(indexed: Driver) -> None:
    names = [f"name_{i}" for i in range(change.MAX_TOKENS + 2)]
    result = check(indexed, "Rename " + ", ".join(names) + ".")

    assert result.unresolved == names[: change.MAX_TOKENS]
    assert result.truncated is True


def test_candidates_of_an_ambiguous_name_are_capped(
    indexed: Driver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(change, "MAX_CANDIDATES", 2)
    result = check(indexed, "Change `__init__` everywhere.")

    assert [c.qualname for c in result.ambiguous[0].candidates] == [
        "app._base.service.BaseService.__init__",
        "app.repos.repository_factory.AllRepositories.__init__",
    ]
    assert result.truncated is True


@pytest.mark.parametrize("description", ["", "   ", "x" * 501])
def test_the_description_must_be_plain_text_of_at_most_500_characters(
    indexed: Driver, description: str
) -> None:
    with pytest.raises(ValueError, match="description"):
        check(indexed, description, ["BaseService"])
