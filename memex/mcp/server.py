"""The Memex MCP server (DESIGN.md section 10): registers the memex.query functions as tools.

No Cypher and no logic here. Each tool checks its codebase (the scope rule), calls one query
function and returns its contract model; scope and argument errors become ToolErrors with
the reason. Every tool is read-only.
"""

from collections.abc import Callable
from typing import Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from neo4j import Driver

from memex.config import Registry, UnknownCodebaseError
from memex.query import calls, change, codebases, docs, impact, symbols
from memex.query.models import (
    CallGraph,
    ChangeCheck,
    ChangeProposal,
    CodebaseList,
    DocSearch,
    Impact,
    SymbolSearch,
)
from memex.query.scope import NotIndexedError, check_codebase

INSTRUCTIONS = """\
Memex answers questions about the structure of indexed Python codebases and their docs:
where symbols are, who calls what, what depends on a symbol, and which doc sections are
relevant. Before a change, check_change lists the code it affects and the documented rules
that apply, each quoted and cited; judge the rules yourself. Every tool except
list_codebases needs a codebase name; call list_codebases first.
A `symbol` is a full dotted qualname or its last segments (`get_one`, `Client.get`). When a
name matches several symbols, the result has symbol=None and the candidates: call again with
one of their qualnames. Results are capped by `limit`; `truncated` says more exist.
Call edges are labeled `exact` or `inferred` (resolved by a unique name only); calls through
attributes whose type is only known at runtime may be missing."""

READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def build_server(driver: Driver, registry: Registry) -> FastMCP:
    mcp = FastMCP("memex", instructions=INSTRUCTIONS)

    def scoped[T](codebase: str, query: Callable[[], T]) -> T:
        try:
            check_codebase(driver, registry, codebase)
            return query()
        except (UnknownCodebaseError, NotIndexedError, ValueError) as error:
            raise ToolError(str(error)) from error

    @mcp.tool(annotations=READ_ONLY)
    def list_codebases() -> CodebaseList:
        """The indexed codebases: source, ref and commit, when indexed, node counts by label,
        edge counts by type, extractors and parse errors."""
        return codebases.list_codebases(driver, registry)

    @mcp.tool(annotations=READ_ONLY)
    def find_symbol(
        codebase: str,
        name: str,
        kind: Literal["module", "class", "function", "any"] = "any",
        limit: int = 10,
    ) -> SymbolSearch:
        """Find modules, classes and functions by name. Best first: the exact qualname, then
        qualnames ending with `name`, then names containing it (ignoring case). Each result
        has its path, line, layer, domain, signature and first docstring line."""
        return scoped(codebase, lambda: symbols.find_symbol(driver, codebase, name, kind, limit))

    @mcp.tool(annotations=READ_ONLY)
    def callers(codebase: str, symbol: str, depth: int = 1, limit: int = 12) -> CallGraph:
        """Functions that call `symbol`, up to `depth` (1 to 5) calls away, each at its
        shortest distance with the call line and confidence. A class stands for its own
        __init__; a class that only inherits __init__ shows no callers, because calls to it
        are recorded on the base class's __init__."""
        return scoped(codebase, lambda: calls.callers(driver, codebase, symbol, depth, limit))

    @mcp.tool(annotations=READ_ONLY)
    def callees(codebase: str, symbol: str, depth: int = 1, limit: int = 12) -> CallGraph:
        """Functions that `symbol` calls, up to `depth` (1 to 5) calls away, each at its
        shortest distance with the call line and confidence. A class stands for its own
        __init__."""
        return scoped(codebase, lambda: calls.callees(driver, codebase, symbol, depth, limit))

    @mcp.tool(annotations=READ_ONLY)
    def impact_of(codebase: str, symbol: str, max_depth: int = 3, limit: int = 8) -> Impact:
        """What depends on `symbol` (and on everything it defines): code that calls, inherits,
        references or imports it, up to `max_depth` (1 to 5) edges away, grouped by layer,
        each with its edge path back. `total` counts all dependents, including those cut by
        `limit`. Also lists up to 5 doc sections that mention the symbol or a dependent, those
        on the symbol first. `truncated` is set when dependents, candidates or docs were cut."""
        return scoped(
            codebase, lambda: impact.impact_of(driver, codebase, symbol, max_depth, limit)
        )

    @mcp.tool(annotations=READ_ONLY)
    def search_docs(codebase: str, query: str, limit: int = 5) -> DocSearch:
        """Full-text search over the codebase's doc sections (headings and text). The query
        is plain text, at most 500 characters. Each hit has its path, heading path, line
        range, a short snippet and the symbols the section mentions; read the file for the
        full section."""
        return scoped(codebase, lambda: docs.search_docs(driver, codebase, query, limit))

    @mcp.tool(annotations=READ_ONLY)
    def check_change(codebase: str, proposal: ChangeProposal) -> ChangeCheck:
        """Check a proposed change before making it. `proposal.description` says what will
        change (plain text, at most 500 characters); `proposal.symbols` optionally names the
        symbols, otherwise code-shaped names in the description are used. Returns the
        resolved, ambiguous and unresolved names, how many dependents each layer has, and up
        to 6 documented rules: one sentence each with its stance (forbids, encourages or
        related, from modal verbs only), path, heading and line range, found because the
        section mentions the changed code or by a search on the description. The stance is a
        hint: read the quote and judge."""
        return scoped(codebase, lambda: change.check_change(driver, codebase, proposal))

    return mcp
