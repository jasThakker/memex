"""list_codebases and the scope check every other tool runs first (DESIGN.md section 10).

Needs Docker. Run with `uv run pytest -m neo4j`.
"""

from pathlib import Path

import pytest
from neo4j import Driver

from memex.cli import stats_from_batch
from memex.config import Registry, UnknownCodebaseError, load_config
from memex.graph.store import ensure_schema, replace_codebase
from memex.ingest.code import index_code
from memex.query.codebases import list_codebases
from memex.query.models import CodebaseInfo
from memex.query.scope import NotIndexedError, check_codebase

pytestmark = pytest.mark.neo4j

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGISTRY = load_config(FIXTURES / "memex.toml")
LAYERED = index_code(REGISTRY.get("layered_app"))
PLAIN = index_code(REGISTRY.get("plainrepo"))


def expected_info(batch_stats: CodebaseInfo) -> CodebaseInfo:
    """The CodebaseInfo part of a CodebaseStats, with the timestamp blanked."""
    data = batch_stats.model_dump(exclude={"layers", "domains"})
    return CodebaseInfo(**{**data, "indexed_at": ""})


def test_list_codebases_is_empty_before_anything_is_indexed(driver: Driver) -> None:
    result = list_codebases(driver, REGISTRY)

    assert result.codebases == []
    assert result.truncated is False


def test_list_codebases_returns_every_indexed_codebase_by_name(driver: Driver) -> None:
    ensure_schema(driver)
    replace_codebase(driver, PLAIN)
    replace_codebase(driver, LAYERED)

    result = list_codebases(driver, REGISTRY)

    assert [info.name for info in result.codebases] == ["layered_app", "plainrepo"]
    blanked = [info.model_copy(update={"indexed_at": ""}) for info in result.codebases]
    assert blanked == [
        expected_info(stats_from_batch(LAYERED)),
        expected_info(stats_from_batch(PLAIN)),
    ]
    assert all(type(info) is CodebaseInfo for info in result.codebases)  # no layers/domains
    assert all(info.indexed_at for info in result.codebases)


def test_list_codebases_leaves_out_codebases_no_longer_registered(driver: Driver) -> None:
    ensure_schema(driver)
    replace_codebase(driver, PLAIN)
    replace_codebase(driver, LAYERED)
    only_layered = Registry(codebases={"layered_app": REGISTRY.get("layered_app")})

    result = list_codebases(driver, only_layered)

    assert [info.name for info in result.codebases] == ["layered_app"]


def test_check_codebase_accepts_a_registered_indexed_codebase(driver: Driver) -> None:
    ensure_schema(driver)
    replace_codebase(driver, LAYERED)

    check_codebase(driver, REGISTRY, "layered_app")  # no error


def test_check_codebase_rejects_an_unknown_name_and_lists_the_registered_ones(
    driver: Driver,
) -> None:
    with pytest.raises(UnknownCodebaseError) as error:
        check_codebase(driver, REGISTRY, "nope")

    assert "'nope'" in str(error.value)
    assert "layered_app, plainrepo" in str(error.value)


def test_check_codebase_rejects_a_registered_codebase_that_is_not_indexed(
    driver: Driver,
) -> None:
    ensure_schema(driver)
    replace_codebase(driver, LAYERED)

    with pytest.raises(NotIndexedError) as error:
        check_codebase(driver, REGISTRY, "plainrepo")

    assert "memex index plainrepo" in str(error.value)
