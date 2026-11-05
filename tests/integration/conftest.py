"""A throwaway Neo4j for `-m neo4j` tests, so they never touch the dev database (DESIGN.md
section 12). One container per test session; each test starts from an empty graph."""

from collections.abc import Iterator

import pytest
from neo4j import Driver, GraphDatabase
from testcontainers.community.neo4j import Neo4jContainer

NEO4J_IMAGE = "neo4j:5.26"  # the same version as docker-compose.yml


@pytest.fixture(scope="session")
def neo4j_container() -> Iterator[Neo4jContainer]:
    with Neo4jContainer(NEO4J_IMAGE) as container:
        yield container


@pytest.fixture(scope="session")
def neo4j_driver(neo4j_container: Neo4jContainer) -> Iterator[Driver]:
    driver = GraphDatabase.driver(
        neo4j_container.get_connection_url(),
        auth=(neo4j_container.username, neo4j_container.password),
    )
    driver.verify_connectivity()
    yield driver
    driver.close()


@pytest.fixture
def driver(neo4j_driver: Driver) -> Iterator[Driver]:
    neo4j_driver.execute_query("MATCH (n) DETACH DELETE n")
    yield neo4j_driver


@pytest.fixture
def neo4j_env(
    neo4j_container: Neo4jContainer, driver: Driver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point `memex.graph.store.connect()` (and so the CLI) at the test container."""
    monkeypatch.setenv("NEO4J_URI", neo4j_container.get_connection_url())
    monkeypatch.setenv("NEO4J_USER", neo4j_container.username)
    monkeypatch.setenv("NEO4J_PASSWORD", neo4j_container.password)
