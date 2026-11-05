"""Doc ingest: load a codebase's Markdown docs, chunk them by heading and link mentions."""

from collections.abc import Sequence
from dataclasses import dataclass

from memex.config import Codebase
from memex.graph.model import DocNode, Edge, Node, ParseError, doc_id
from memex.ingest.docs.chunker import chunk, split_lines
from memex.ingest.docs.loader import load_docs
from memex.ingest.docs.mentions import MentionTargets, link_mentions


@dataclass(frozen=True, kw_only=True)
class DocIndex:
    nodes: tuple[DocNode, ...] = ()
    edges: tuple[Edge, ...] = ()
    parse_errors: tuple[ParseError, ...] = ()


def index_docs(codebase: Codebase, code_nodes: Sequence[Node]) -> DocIndex:
    """One Doc node per heading chunk of every doc file, in path order, then file order, and
    the MENTIONS edges from each chunk to the `code_nodes` it names. Mentions are read from
    the chunk's source lines, so a backticked name in the heading line counts."""
    files, errors = load_docs(codebase)
    targets = MentionTargets(code_nodes)
    nodes: list[DocNode] = []
    edges: list[Edge] = []
    for file in files:
        lines = split_lines(file.text)
        for piece in chunk(file.text):
            node = DocNode(
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
            source = "\n".join(lines[piece.start_line - 1 : piece.end_line])
            nodes.append(node)
            edges += link_mentions(node.id, source, targets)
    return DocIndex(nodes=tuple(nodes), edges=tuple(edges), parse_errors=tuple(errors))
