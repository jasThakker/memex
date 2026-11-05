"""The graph model: nodes, edges and the batch that ingest hands to the store.

See DESIGN.md section 7. Frozen after Phase 3; changing it needs an ADR in docs/decisions/.
Paths are relative to the codebase root, with forward slashes. `line` on a class or function
is its `class` or `def` line, not its first decorator. Layer and domain stay None until the
classifier sets them.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

EdgeKind = Literal["DEFINES", "IMPORTS", "CALLS", "INHERITS", "REFERENCES", "MENTIONS"]
Confidence = Literal["exact", "inferred", "ambiguous"]
MentionMatch = Literal["qualname", "path", "backtick_name"]


def code_id(codebase: str, qualname: str) -> str:
    """Id of a Module, Class or Function node."""
    return f"{codebase}:{qualname}"


def external_id(codebase: str, dotted: str) -> str:
    """Id of an External node: a name imported or inherited from outside the codebase."""
    return f"{codebase}:ext:{dotted}"


def doc_id(codebase: str, path: str, anchor: str) -> str:
    """Id of a Doc node: one heading-delimited chunk of a Markdown file."""
    return f"{codebase}:doc:{path}#{anchor}"


@dataclass(frozen=True, kw_only=True)
class CodebaseNode:
    id: str  # the codebase name
    codebase: str  # also the name, so per-codebase deletes catch it
    name: str
    root: str
    indexed_at: str  # ISO 8601
    source: str | None = None
    ref: str | None = None
    commit: str | None = None
    extractors: tuple[str, ...] = ()
    parse_errors: int = 0


@dataclass(frozen=True, kw_only=True)
class ModuleNode:
    id: str
    codebase: str
    qualname: str
    path: str
    layer: str | None = None
    domain: str | None = None
    docstring: str | None = None


@dataclass(frozen=True, kw_only=True)
class ClassNode:
    id: str
    codebase: str
    name: str
    qualname: str
    path: str
    line: int
    end_line: int
    layer: str | None = None
    domain: str | None = None
    docstring: str | None = None
    tablename: str | None = None


@dataclass(frozen=True, kw_only=True)
class FunctionNode:
    id: str
    codebase: str
    name: str
    qualname: str
    path: str
    line: int
    end_line: int
    signature: str
    is_method: bool
    is_async: bool
    layer: str | None = None
    domain: str | None = None
    docstring: str | None = None


@dataclass(frozen=True, kw_only=True)
class ExternalNode:
    id: str
    codebase: str
    name: str


@dataclass(frozen=True, kw_only=True)
class DocNode:
    id: str
    codebase: str
    path: str
    heading_path: str
    anchor: str
    text: str
    start_line: int
    end_line: int
    kind: str = "doc"


Node = CodebaseNode | ModuleNode | ClassNode | FunctionNode | ExternalNode | DocNode


@dataclass(frozen=True, kw_only=True)
class Edge:
    """One relationship. Only the properties its kind uses are set (DESIGN.md section 7)."""

    kind: EdgeKind
    source: str
    target: str
    line: int | None = None
    confidence: Confidence | None = None
    names: tuple[str, ...] = ()
    position: int | None = None
    ref_kind: str | None = None
    attr: str | None = None
    extractor: str | None = None
    match: MentionMatch | None = None


@dataclass(frozen=True, kw_only=True)
class ParseError:
    path: str
    line: int | None
    message: str


@dataclass(frozen=True, kw_only=True)
class IndexStats:
    files: int = 0
    parse_errors: tuple[ParseError, ...] = ()
    unresolved_calls: int = 0
    dropped_duplicates: tuple[str, ...] = ()  # definitions whose id a module already had
    layers: Mapping[str, int] = field(default_factory=dict)
    domains: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class GraphBatch:
    """Everything ingest produced for one codebase, ready for a full re-index."""

    codebase: str
    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()
    stats: IndexStats = field(default_factory=IndexStats)
