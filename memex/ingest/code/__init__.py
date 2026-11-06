"""Code ingest: walk, parse, classify and link one codebase into a GraphBatch."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from memex.config import Codebase, ConfigError
from memex.graph.model import (
    ClassNode,
    CodebaseNode,
    Edge,
    GraphBatch,
    IndexStats,
    ModuleNode,
    ParseError,
)
from memex.ingest.code.classify import classify
from memex.ingest.code.extractors import EXTRACTORS, Extractor
from memex.ingest.code.extractors.base import CLASS_PROPERTIES
from memex.ingest.code.parser import ParsedModule, parse_module
from memex.ingest.code.resolver import (
    SymbolTable,
    link_calls,
    link_imports,
    link_inherits,
    link_uses,
)
from memex.ingest.code.walker import walk


def index_code(codebase: Codebase) -> GraphBatch:
    """Every module, class and function of a codebase with its DEFINES, IMPORTS, INHERITS,
    CALLS and USES edges (a USES edge is left out where an extractor's REFERENCES links the
    same pair), the External nodes those point at (one per id) and the unresolved call count.
    The extractors listed for the codebase add their edges and class properties last; an
    unknown extractor name is a ConfigError, raised before anything is read.

    A file that fails to parse is recorded in the stats and skipped. Node ids are unique:
    if a definition has the id of a module (say `def utils()` in `pkg/__init__.py` next to
    `pkg/utils.py`), the module wins; the definition and everything inside it are dropped
    and recorded before imports are linked, so no edge points at a dropped node.
    """
    extractors = _extractors(codebase)
    sources = walk(codebase)
    parsed: list[ParsedModule] = []
    errors: list[ParseError] = []
    for source in sources:
        result = parse_module(codebase.name, source, (codebase.root / source.path).read_bytes())
        if isinstance(result, ParseError):
            errors.append(result)
        else:
            parsed.append(result)

    modules, dropped = _labeled_without_duplicates(codebase, parsed)
    imports, import_externals = link_imports(codebase.name, modules)
    symbols = SymbolTable(modules)
    inherits, inherit_externals = link_inherits(codebase.name, symbols)
    calls, unresolved_calls = link_calls(codebase.name, symbols)
    extracted, properties = _run_extractors(extractors, modules, symbols)
    referenced = {(edge.source, edge.target) for edge in extracted if edge.kind == "REFERENCES"}
    uses = [
        edge
        for edge in link_uses(codebase.name, symbols)
        if (edge.source, edge.target) not in referenced
    ]
    externals = {node.id: node for node in (*import_externals, *inherit_externals)}
    code_nodes = [
        replace(node, **properties[node.id])
        if isinstance(node, ClassNode) and node.id in properties
        else node
        for module in modules
        for node in module.nodes
    ]
    defines = [edge for module in modules for edge in module.defines]
    module_nodes = [node for node in code_nodes if isinstance(node, ModuleNode)]

    codebase_node = CodebaseNode(
        id=codebase.name,
        codebase=codebase.name,
        name=codebase.name,
        root=str(codebase.root),
        indexed_at=datetime.now(UTC).isoformat(timespec="seconds"),
        source=codebase.source,
        ref=codebase.ref,
        commit=codebase.commit,
        extractors=codebase.extractors,
        files=len(sources),
        parse_errors=len(errors),
        unresolved_calls=unresolved_calls,
    )
    stats = IndexStats(
        files=len(sources),
        parse_errors=tuple(errors),
        unresolved_calls=unresolved_calls,
        dropped_duplicates=tuple(dropped),
        layers=dict(Counter(node.layer for node in module_nodes if node.layer)),
        domains=dict(Counter(node.domain for node in module_nodes if node.domain)),
    )
    return GraphBatch(
        codebase=codebase.name,
        nodes=(codebase_node, *code_nodes, *externals.values()),
        edges=(*defines, *imports, *inherits, *calls, *uses, *extracted),
        stats=stats,
    )


def _extractors(codebase: Codebase) -> list[Extractor]:
    unknown = [name for name in codebase.extractors if name not in EXTRACTORS]
    if unknown:
        known = ", ".join(sorted(EXTRACTORS))
        raise ConfigError(
            f"codebase {codebase.name!r}: unknown extractor {unknown[0]!r}; known: {known}"
        )
    return [EXTRACTORS[name]() for name in codebase.extractors]


def _run_extractors(
    extractors: Sequence[Extractor], modules: Sequence[ParsedModule], symbols: SymbolTable
) -> tuple[list[Edge], dict[str, dict[str, str]]]:
    """Edges and class properties from every extractor, in the order listed."""
    edges: list[Edge] = []
    properties: dict[str, dict[str, str]] = {}
    for extractor in extractors:
        edges += extractor.extract(modules, symbols)
        for class_id, values in extractor.class_properties(modules, symbols).items():
            undeclared = set(values) - CLASS_PROPERTIES
            if undeclared:
                raise ValueError(f"{extractor.name} sets undeclared properties {undeclared}")
            properties.setdefault(class_id, {}).update(values)
    return edges, properties


def _labeled_without_duplicates(
    codebase: Codebase, modules: Sequence[ParsedModule]
) -> tuple[list[ParsedModule], list[str]]:
    """Modules whose nodes carry their layer and domain, minus definitions whose id is
    already taken and everything defined inside them, plus the ids that were dropped."""
    seen = {module.nodes[0].id for module in modules}
    kept_modules: list[ParsedModule] = []
    dropped: list[str] = []
    for module in modules:
        layer, domain = classify(codebase, module.source)
        parent_of = {edge.target: edge.source for edge in module.defines}
        dropped_here: set[str] = set()
        nodes = [replace(module.nodes[0], layer=layer, domain=domain)]
        for node in module.nodes[1:]:
            if node.id in seen or parent_of[node.id] in dropped_here:
                dropped_here.add(node.id)
                dropped.append(node.id)
                continue
            seen.add(node.id)
            nodes.append(replace(node, layer=layer, domain=domain))
        defines = tuple(edge for edge in module.defines if edge.target not in dropped_here)
        kept_modules.append(replace(module, nodes=tuple(nodes), defines=defines))
    return kept_modules, dropped
