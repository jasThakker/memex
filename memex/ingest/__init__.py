"""Turn source files and docs into a GraphBatch. Never imports neo4j."""

from dataclasses import replace

from memex.config import Codebase
from memex.graph.model import CodebaseNode, GraphBatch
from memex.ingest.code import index_code
from memex.ingest.docs import index_docs


def index_codebase(codebase: Codebase) -> GraphBatch:
    """The whole codebase in one batch: code first, then the Doc nodes and the MENTIONS edges
    from them to that code. Doc parse errors follow the code parse errors in the stats, and
    the Codebase node's `parse_errors` counts both; its `files` counts code files only."""
    code = index_code(codebase)
    docs = index_docs(codebase, code.nodes)
    errors = (*code.stats.parse_errors, *docs.parse_errors)
    nodes = tuple(
        replace(node, parse_errors=len(errors)) if isinstance(node, CodebaseNode) else node
        for node in code.nodes
    )
    return replace(
        code,
        nodes=(*nodes, *docs.nodes),
        edges=(*code.edges, *docs.edges),
        stats=replace(code.stats, parse_errors=errors),
    )
