"""The `memex` command: `memex index <codebase>`, `memex stats <codebase>` and `memex serve`.

`index` parses the codebase, replaces it in Neo4j and prints a summary; `stats` prints the same
summary from what Neo4j holds; `serve` runs the read-only MCP server on stdio for every
codebase in memex.toml. Exit codes: 0 success, 1 a database problem or a codebase that is not
indexed, 2 a usage or config error (including a missing package directory or a malformed
NEO4J_URI).
"""

import argparse
import os
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence

from neo4j.exceptions import AuthError, ConfigurationError, Neo4jError, ServiceUnavailable

from memex.config import Codebase, ConfigError, Registry, UnknownCodebaseError, load_config
from memex.graph.model import CodebaseNode, GraphBatch, ModuleNode
from memex.graph.store import connect, ensure_schema, label_of, replace_codebase
from memex.ingest import index_codebase
from memex.ingest.code.walker import WalkerError
from memex.mcp.server import build_server
from memex.query.codebases import codebase_stats
from memex.query.models import CodebaseStats

MAX_PARSE_ERRORS_SHOWN = 10


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        registry = load_config(args.config)
        codebase = None if args.command == "serve" else registry.get(args.codebase)
    except (ConfigError, UnknownCodebaseError) as error:
        print(f"memex: {error}", file=sys.stderr)
        return 2
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    try:
        if args.command == "serve":
            return _serve(registry)
        assert codebase is not None
        if args.command == "index":
            return _index(codebase)
        return _stats(codebase.name)
    except (ConfigError, WalkerError) as error:
        print(f"memex: {error}", file=sys.stderr)
        return 2
    except ConfigurationError as error:
        print(f"memex: invalid NEO4J_URI {uri!r}: {error}", file=sys.stderr)
        return 2
    except AuthError:
        user = os.environ.get("NEO4J_USER", "neo4j")
        print(
            f"memex: Neo4j rejected the credentials for user {user!r} at {uri}; "
            "check NEO4J_USER and NEO4J_PASSWORD",
            file=sys.stderr,
        )
        return 1
    except ServiceUnavailable as error:
        print(f"memex: cannot reach Neo4j at {uri}: {error}", file=sys.stderr)
        print("memex: is it running? `docker compose up -d neo4j`", file=sys.stderr)
        return 1
    except Neo4jError as error:
        action = "writing" if args.command == "index" else "reading"
        target = codebase.name if codebase else "the graph"
        print(f"memex: Neo4j error while {action} {target}: {error}", file=sys.stderr)
        return 1


def stats_from_batch(batch: GraphBatch) -> CodebaseStats:
    """What `codebase_stats` will read back once the batch is stored."""
    codebase = next(node for node in batch.nodes if isinstance(node, CodebaseNode))
    modules = [node for node in batch.nodes if isinstance(node, ModuleNode)]
    return CodebaseStats(
        name=codebase.name,
        source=codebase.source,
        ref=codebase.ref,
        commit=codebase.commit,
        indexed_at=codebase.indexed_at,
        files=codebase.files,
        extractors=list(codebase.extractors),
        parse_errors=codebase.parse_errors,
        unresolved_calls=codebase.unresolved_calls,
        nodes=dict(Counter(label_of(n) for n in batch.nodes if not isinstance(n, CodebaseNode))),
        edges=dict(Counter(edge.kind for edge in batch.edges)),
        layers=dict(Counter(node.layer for node in modules if node.layer)),
        domains=dict(Counter(node.domain for node in modules if node.domain)),
    )


def format_stats(stats: CodebaseStats) -> str:
    source = "local"
    if stats.source:
        source = f"{stats.source} @ {stats.ref} ({(stats.commit or '')[:7]})"
    lines = [
        f"{stats.name}: {stats.files} files, {stats.parse_errors} parse errors, "
        f"{stats.unresolved_calls} unresolved calls",
        f"  source:    {source}",
        f"  indexed:   {stats.indexed_at}, extractors: {', '.join(stats.extractors) or 'none'}",
        f"  nodes:     {_counts(stats.nodes)}",
        f"  edges:     {_counts(stats.edges)}",
        f"  layers:    {_counts(stats.layers)}",
        f"  domains:   {_counts(stats.domains)}",
    ]
    return "\n".join(lines) + "\n"


def _index(codebase: Codebase) -> int:
    started = time.perf_counter()
    batch = index_codebase(codebase)
    with connect() as driver:
        driver.verify_connectivity()  # fail fast instead of retrying for 30 s
        ensure_schema(driver)
        replace_codebase(driver, batch)
    print(format_stats(stats_from_batch(batch)), end="")
    for error in batch.stats.parse_errors[:MAX_PARSE_ERRORS_SHOWN]:
        print(f"  parse error: {error.path}:{error.line}: {error.message}")
    print(f"  took:      {time.perf_counter() - started:.1f} s")
    return 0


def _stats(name: str) -> int:
    with connect() as driver:
        driver.verify_connectivity()
        stats = codebase_stats(driver, name)
    if stats is None:
        print(f"memex: {name} is not indexed; run `memex index {name}`", file=sys.stderr)
        return 1
    print(format_stats(stats), end="")
    return 0


def _serve(registry: Registry) -> int:
    with connect() as driver:
        driver.verify_connectivity()  # fail at start, not on the first tool call
        build_server(driver, registry).run(transport="stdio", show_banner=False)
    return 0


def _counts(counts: Mapping[str, int]) -> str:
    """`a 3, b 2`: largest first, ties by name."""
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{key} {count}" for key, count in ordered) or "none"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memex", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("index", "parse a codebase and replace it in Neo4j"),
        ("stats", "print what Neo4j holds for a codebase"),
    ):
        sub = commands.add_parser(command, help=help_text)
        sub.add_argument("codebase", help="a codebase name from memex.toml")
        sub.add_argument("--config", default="memex.toml", help="path to memex.toml")
    serve = commands.add_parser("serve", help="run the read-only MCP server on stdio")
    serve.add_argument("--config", default="memex.toml", help="path to memex.toml")
    return parser
