"""`memex index` and `memex stats` against the test Neo4j, and `codebase_stats`.

Needs Docker. Run with `uv run pytest -m neo4j`.
"""

from pathlib import Path

import pytest
from neo4j import Driver

from memex.cli import format_stats, main, stats_from_batch
from memex.config import load_config
from memex.ingest.code import index_code
from memex.query.codebases import codebase_stats

pytestmark = pytest.mark.neo4j

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CONFIG = str(FIXTURES / "memex.toml")


@pytest.mark.usefixtures("neo4j_env")
def test_index_then_stats_print_the_same_summary(
    driver: Driver, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["index", "layered_app", "--config", CONFIG]) == 0
    indexed = capsys.readouterr().out

    assert main(["stats", "layered_app", "--config", CONFIG]) == 0
    stats = capsys.readouterr().out

    assert indexed.startswith(stats)  # index adds only a timing line after the summary
    assert "layered_app: 27 files, 0 parse errors, 5 unresolved calls" in stats


@pytest.mark.usefixtures("neo4j_env")
def test_codebase_stats_reads_back_what_was_indexed(driver: Driver) -> None:
    batch = index_code(load_config(FIXTURES / "memex.toml").get("layered_app"))
    assert main(["index", "layered_app", "--config", CONFIG]) == 0

    stored = codebase_stats(driver, "layered_app")

    assert stored is not None
    expected = stats_from_batch(batch)
    assert stored.model_copy(update={"indexed_at": ""}) == expected.model_copy(
        update={"indexed_at": ""}
    )
    assert format_stats(stored).splitlines()[0] == format_stats(expected).splitlines()[0]


def test_codebase_stats_is_none_for_a_codebase_never_indexed(driver: Driver) -> None:
    assert codebase_stats(driver, "plainrepo") is None


@pytest.mark.usefixtures("neo4j_env")
def test_stats_for_a_codebase_never_indexed_exits_1(
    driver: Driver, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["stats", "plainrepo", "--config", CONFIG]) == 1
    assert "plainrepo is not indexed; run `memex index plainrepo`" in capsys.readouterr().err


def test_an_unreachable_database_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:1")  # nothing listens there

    assert main(["stats", "layered_app", "--config", CONFIG]) == 1
    assert "cannot reach Neo4j at bolt://localhost:1" in capsys.readouterr().err
