"""The scope rule (DESIGN.md section 10): every tool except list_codebases names its codebase,
and the name must be registered in memex.toml and indexed. Memex never infers scope."""

from neo4j import Driver, RoutingControl

from memex.config import Registry


class NotIndexedError(LookupError):
    """A codebase registered in memex.toml that Neo4j holds nothing for."""


# The scope rule, run by scoped() before every tool except list_codebases: the name must be in
# memex.toml AND indexed in Neo4j.
def check_codebase(driver: Driver, registry: Registry, name: str) -> None:
    """Raise UnknownCodebaseError (listing the registered names) or NotIndexedError."""
    registry.get(name)
    rows, _, _ = driver.execute_query(
        "MATCH (c:Codebase {id: $name}) RETURN count(c) AS n",
        name=name,
        routing_=RoutingControl.READ,
    )
    if rows[0]["n"] == 0:
        raise NotIndexedError(f"codebase {name!r} is not indexed; run `memex index {name}`")
