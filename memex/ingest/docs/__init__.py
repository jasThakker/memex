"""Doc ingest: load a codebase's Markdown docs, chunk them by heading and link mentions."""

from collections.abc import Sequence
from dataclasses import dataclass

from memex.config import Codebase
from memex.graph.model import DocNode, Edge, Node, ParseError, doc_id
from memex.ingest.docs.chunker import chunk
from memex.ingest.docs.loader import load_docs


@dataclass(frozen=True, kw_only=True)
class DocIndex:
    nodes: tuple[DocNode, ...] = ()
    edges: tuple[Edge, ...] = ()
    parse_errors: tuple[ParseError, ...] = ()


def index_docs(codebase: Codebase, code_nodes: Sequence[Node]) -> DocIndex:
    """One Doc node per heading chunk of every doc file, in path order, then file order.
    `code_nodes` are the targets MENTIONS edges may point at."""
    files, errors = load_docs(codebase)
    nodes = tuple(
        DocNode(
            id=doc_id(codebase.name, file.path, piece.anchor),
            codebase=codebase.name,
            path=file.path,
            heading_path=piece.heading_path,
            anchor=piece.anchor,
            text=piece.text,
            start_line=piece.start_line,
            end_line=piece.end_line,
            kind=file.kind,
        )
        for file in files
        for piece in chunk(file.text)
    )
    return DocIndex(nodes=nodes, parse_errors=tuple(errors))
