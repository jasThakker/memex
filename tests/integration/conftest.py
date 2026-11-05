"""A throwaway Neo4j for `-m neo4j` tests, so they never touch the dev database (DESIGN.md
section 12). One container per test session; each test starts from an empty graph."""

from collections.abc import Iterator

import pytest
from neo4j import Driver, GraphDatabase
from testcontainers.community.neo4j import Neo4jContainer

NEO4J_IMAGE = "neo4j:5.26"  # the same version as docker-compose.yml


@pytest.fixture(scope="session")
def neo4j_driver() -> Iterator[Driver]:
    with Neo4jContainer(NEO4J_IMAGE) as container:
        driver = GraphDatabase.driver(
            container.get_connection_url(), auth=(container.username, container.password)
        )
        driver.verify_connectivity()
        yield driver
        driver.close()


@pytest.fixture
def driver(neo4j_driver: Driver) -> Iterator[Driver]:
    neo4j_driver.execute_query("MATCH (n) DETACH DELETE n")
    yield neo4j_driver
