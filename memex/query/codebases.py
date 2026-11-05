"""Read what is stored about one codebase (DESIGN.md section 10: list_codebases, memex stats)."""

from neo4j import Driver, RoutingControl

from memex.query.models import CodebaseStats


def codebase_stats(driver: Driver, codebase: str) -> CodebaseStats | None:
    """Counts for one indexed codebase, or None if it was never indexed.

    Node counts leave out the Codebase node itself; layer and domain counts are per module.
    """
    rows, _, _ = driver.execute_query(
        "MATCH (c:Codebase {id: $codebase}) RETURN properties(c) AS props",
        codebase=codebase,
        routing_=RoutingControl.READ,
    )
    if not rows:
        return None
    props = rows[0]["props"]

    nodes, _, _ = driver.execute_query(
        "MATCH (n {codebase: $codebase}) WHERE NOT n:Codebase "
        "RETURN labels(n)[0] AS key, count(*) AS n",
        codebase=codebase,
        routing_=RoutingControl.READ,
    )
    edges, _, _ = driver.execute_query(
        "MATCH (n {codebase: $codebase})-[r]->() RETURN type(r) AS key, count(*) AS n",
        codebase=codebase,
        routing_=RoutingControl.READ,
    )
    layers, _, _ = driver.execute_query(
        "MATCH (m:Module {codebase: $codebase}) WHERE m.layer IS NOT NULL "
        "RETURN m.layer AS key, count(*) AS n",
        codebase=codebase,
        routing_=RoutingControl.READ,
    )
    domains, _, _ = driver.execute_query(
        "MATCH (m:Module {codebase: $codebase}) WHERE m.domain IS NOT NULL "
        "RETURN m.domain AS key, count(*) AS n",
        codebase=codebase,
        routing_=RoutingControl.READ,
    )
    return CodebaseStats(
        name=props["name"],
        source=props.get("source"),
        ref=props.get("ref"),
        commit=props.get("commit"),
        indexed_at=props["indexed_at"],
        files=props.get("files", 0),
        extractors=props.get("extractors", []),
        parse_errors=props.get("parse_errors", 0),
        unresolved_calls=props.get("unresolved_calls", 0),
        nodes={row["key"]: row["n"] for row in nodes},
        edges={row["key"]: row["n"] for row in edges},
        layers={row["key"]: row["n"] for row in layers},
        domains={row["key"]: row["n"] for row in domains},
    )
