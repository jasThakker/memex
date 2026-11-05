"""The `memex` command line, without a database: arguments, errors and the summary text."""

from collections import Counter
from pathlib import Path

import pytest

from memex.cli import format_stats, main, stats_from_batch
from memex.config import load_config
from memex.graph.store import label_of
from memex.ingest.code import index_code
from memex.query.models import CodebaseStats

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CONFIG = str(FIXTURES / "memex.toml")


def test_stats_from_batch_counts_what_the_store_will_hold() -> None:
    batch = index_code(load_config(FIXTURES / "memex.toml").get("layered_app"))

    stats = stats_from_batch(batch)

    assert (stats.name, stats.files, stats.parse_errors, stats.unresolved_calls) == (
        "layered_app",
        27,
        0,
        5,
    )
    assert stats.extractors == ["sqlalchemy"]
    # Counted independently from the batch; the Codebase node itself is not a count.
    assert stats.nodes == dict(
        Counter(label_of(node) for node in batch.nodes if label_of(node) != "Codebase")
    )
    assert stats.edges == dict(Counter(edge.kind for edge in batch.edges))
    assert (stats.edges["CALLS"], stats.edges["REFERENCES"]) == (14, 3)
    # From the fixture tree: db/models holds __init__, _model_base, orders and users; the
    # order domain is routes/orders (2), repos, schema, services/order_services (2), db/models.
    assert stats.layers["db_models"] == 4
    assert stats.domains["order"] == 7


def test_format_stats_prints_counts_largest_first() -> None:
    stats = CodebaseStats(
        name="shop",
        source="https://example.com/shop",
        ref="v1",
        commit="a" * 40,
        indexed_at="2026-11-05T10:00:00+00:00",
        files=3,
        extractors=["sqlalchemy"],
        parse_errors=1,
        unresolved_calls=7,
        nodes={"Class": 2, "Module": 3},
        edges={"DEFINES": 4, "CALLS": 9},
        layers={"routes": 1, "services": 2},
        domains={"user": 3},
    )

    assert format_stats(stats) == (
        "shop: 3 files, 1 parse errors, 7 unresolved calls\n"
        "  source:    https://example.com/shop @ v1 (aaaaaaa)\n"
        "  indexed:   2026-11-05T10:00:00+00:00, extractors: sqlalchemy\n"
        "  nodes:     Module 3, Class 2\n"
        "  edges:     CALLS 9, DEFINES 4\n"
        "  layers:    services 2, routes 1\n"
        "  domains:   user 3\n"
    )


def test_format_stats_for_a_local_codebase_without_extractors() -> None:
    stats = CodebaseStats(name="lib", indexed_at="t", files=0)

    assert format_stats(stats) == (
        "lib: 0 files, 0 parse errors, 0 unresolved calls\n"
        "  source:    local\n"
        "  indexed:   t, extractors: none\n"
        "  nodes:     none\n"
        "  edges:     none\n"
        "  layers:    none\n"
        "  domains:   none\n"
    )


@pytest.mark.parametrize("command", ["index", "stats"])
def test_unknown_codebase_exits_2_and_lists_the_registered_names(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([command, "nope", "--config", CONFIG]) == 2

    error = capsys.readouterr().err
    assert "unknown codebase 'nope'" in error
    assert "layered_app" in error and "plainrepo" in error


def test_missing_config_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["stats", "x", "--config", str(tmp_path / "missing.toml")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit) as raised:
        main([])
    assert raised.value.code == 2


def test_a_missing_package_directory_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The usual first-run mistake: indexing before scripts/fetch_codebases.py has run.
    config = tmp_path / "memex.toml"
    config.write_text('[codebases.ghost]\nroot = "vendor/ghost"\npackages = ["ghost"]\n')

    assert main(["index", "ghost", "--config", str(config)]) == 2
    assert "package directory 'ghost' not found" in capsys.readouterr().err


def test_an_unreachable_database_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:1")  # nothing listens there

    assert main(["stats", "layered_app", "--config", CONFIG]) == 1
    error = capsys.readouterr().err
    assert "cannot reach Neo4j at bolt://localhost:1" in error
    assert "docker compose up -d neo4j" in error


def test_a_malformed_neo4j_uri_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NEO4J_URI", "nonsense://localhost")

    assert main(["stats", "layered_app", "--config", CONFIG]) == 2
    assert "invalid NEO4J_URI 'nonsense://localhost'" in capsys.readouterr().err


class FakeDriver:
    def __enter__(self) -> FakeDriver:
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def verify_connectivity(self) -> None:
        pass


class FakeServer:
    def __init__(self) -> None:
        self.ran_with: dict[str, object] | None = None

    def run(self, **kwargs: object) -> None:
        self.ran_with = kwargs


def test_serve_builds_the_server_over_the_registry_and_runs_it_on_stdio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver, server = FakeDriver(), FakeServer()
    built: list[tuple[object, list[str]]] = []

    def fake_build(d: object, registry: object) -> FakeServer:
        built.append((d, registry.names()))  # type: ignore[attr-defined]
        return server

    monkeypatch.setattr("memex.cli.connect", lambda: driver)
    monkeypatch.setattr("memex.cli.build_server", fake_build)

    assert main(["serve", "--config", str(FIXTURES / "memex.toml")]) == 0
    assert built == [(driver, ["layered_app", "plainrepo"])]
    assert server.ran_with is not None and server.ran_with["transport"] == "stdio"


def test_serve_with_a_bad_config_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["serve", "--config", str(tmp_path / "missing.toml")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_serve_takes_no_codebase() -> None:
    with pytest.raises(SystemExit):
        main(["serve", "layered_app"])
