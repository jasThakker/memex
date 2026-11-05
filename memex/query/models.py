"""The tool contract: Pydantic models every MCP tool returns (DESIGN.md section 10).

Frozen after Phase 3; changing it needs an ADR in docs/decisions/ (ADR-001).
- Results hold locations, signatures and first docstring lines, never source bodies.
- Every result that holds a list carries `truncated`, True when a limit cut it short.
- Code is always referred to by qualname, through SymbolRef.
- A tool that takes a `symbol` returns `symbol=None` and the matching `candidates` when a
  short name is ambiguous, and both empty when nothing matches. It never guesses.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from memex.graph.model import Confidence

SymbolKind = Literal["module", "class", "function"]
ImpactEdge = Literal["CALLS", "INHERITS", "REFERENCES", "IMPORTS"]


class Contract(BaseModel):
    """Base for every contract model: immutable, and unknown fields are an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# Shared pieces


class SymbolRef(Contract):
    """Where a module, class or function is. `line` is None for modules."""

    qualname: str
    kind: SymbolKind
    path: str
    line: int | None = None
    layer: str | None = None
    domain: str | None = None


class Symbol(SymbolRef):
    signature: str | None = None  # functions only
    docstring: str | None = None  # first line


class Citation(Contract):
    path: str
    heading_path: str
    start_line: int
    end_line: int


class DocRef(Citation):
    mentions: list[str] = []  # qualnames of the symbols this doc section mentions


# list_codebases


class CodebaseInfo(Contract):
    name: str
    source: str | None = None
    ref: str | None = None
    commit: str | None = None
    indexed_at: str  # ISO 8601
    files: int
    extractors: list[str] = []
    parse_errors: int = 0
    unresolved_calls: int = 0
    nodes: dict[str, int] = {}  # count by label
    edges: dict[str, int] = {}  # count by type


class CodebaseList(Contract):
    codebases: list[CodebaseInfo]
    truncated: bool = False


class CodebaseStats(CodebaseInfo):
    """`memex stats`: a CodebaseInfo plus module counts by layer and by domain."""

    layers: dict[str, int] = {}
    domains: dict[str, int] = {}


# find_symbol


class SymbolSearch(Contract):
    codebase: str
    query: str
    kind: Literal["module", "class", "function", "any"]
    symbols: list[Symbol]
    truncated: bool = False


# callers, callees


class CallHop(Contract):
    """One function reached at `distance`. `via` is the qualname it calls (for callers) or is
    called by (for callees), one step closer to the starting symbol."""

    function: SymbolRef
    via: str
    line: int | None
    confidence: Confidence
    distance: int


class CallGraph(Contract):
    codebase: str
    symbol: SymbolRef | None
    candidates: list[SymbolRef] = []
    direction: Literal["callers", "callees"]
    depth: int
    calls: list[CallHop] = []
    truncated: bool = False


# impact_of


class PathStep(Contract):
    """One edge on the way from a dependent back to the starting symbol."""

    edge: ImpactEdge
    to: str  # qualname


class Dependent(Contract):
    symbol: SymbolRef
    distance: int
    path: list[PathStep]


class LayerGroup(Contract):
    layer: str | None  # None for code outside any labeled layer
    dependents: list[Dependent]


class Impact(Contract):
    codebase: str
    symbol: SymbolRef | None
    candidates: list[SymbolRef] = []
    max_depth: int
    total: int = 0  # dependents found, before any truncation
    layers: list[LayerGroup] = []
    docs: list[DocRef] = []  # doc sections that mention any dependent
    truncated: bool = False


# search_docs


class DocHit(Contract):
    path: str
    heading_path: str
    kind: str
    start_line: int
    end_line: int
    snippet: str
    mentions: list[str] = []
    score: float


class DocSearch(Contract):
    codebase: str
    query: str
    hits: list[DocHit]
    truncated: bool = False


# check_change


class ChangeProposal(Contract):
    """Input. Explicit symbols are preferred; if empty, the description is matched."""

    description: str
    symbols: list[str] = []


class LayerCount(Contract):
    layer: str | None
    count: int


class ImpactSummary(Contract):
    total: int
    layers: list[LayerCount]


class Guideline(Contract):
    stance: Literal["forbids", "encourages", "related"]
    quote: str  # the sentence
    citation: Citation
    matched_on: Literal["mention", "search"]


class AmbiguousName(Contract):
    """A short name in a proposal that matches more than one symbol."""

    name: str
    candidates: list[SymbolRef]


class ChangeCheck(Contract):
    codebase: str
    resolved_symbols: list[SymbolRef]
    ambiguous: list[AmbiguousName] = []  # never guessed: the caller picks
    unresolved: list[str]
    affected: ImpactSummary
    guidelines: list[Guideline]
    truncated: bool = False


# module_summary (stretch)


class ClassSummary(Contract):
    name: str
    line: int
    bases: list[str]
    methods: list[str]


class FunctionSummary(Contract):
    name: str
    line: int
    signature: str


class ModuleSummary(Contract):
    """Layer and domain are on `module`."""

    codebase: str
    module: SymbolRef | None
    candidates: list[SymbolRef] = []
    docstring: str | None = None
    classes: list[ClassSummary] = []
    functions: list[FunctionSummary] = []
    imports: list[str] = []  # in-codebase modules it imports
    imported_by: int = 0
    docs: list[DocRef] = []
    truncated: bool = False
