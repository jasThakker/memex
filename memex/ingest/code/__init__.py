"""Code ingest: walk, parse, link imports and classify one codebase into a GraphBatch."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from memex.config import Codebase
from memex.graph.model import CodebaseNode, GraphBatch, IndexStats, ModuleNode, ParseError
from memex.ingest.code.classify import classify
from memex.ingest.code.parser import ParsedModule, parse_module
from memex.ingest.code.resolver import link_imports
from memex.ingest.code.walker import walk


def index_code(codebase: Codebase) -> GraphBatch:
    """Every module, class and function of a codebase with its DEFINES and IMPORTS edges.

    A file that fails to parse is recorded in the stats and skipped. Node ids are unique:
    if a definition has the id of a module (say `def utils()` in `pkg/__init__.py` next to
    `pkg/utils.py`), the module wins; the definition and everything inside it are dropped
    and recorded before imports are linked, so no edge points at a dropped node.
    """
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
    imports, externals = link_imports(codebase.name, modules)
    code_nodes = [node for module in modules for node in module.nodes]
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
        parse_errors=len(errors),
    )
    stats = IndexStats(
        files=len(sources),
        parse_errors=tuple(errors),
        dropped_duplicates=tuple(dropped),
        layers=dict(Counter(node.layer for node in module_nodes if node.layer)),
        domains=dict(Counter(node.domain for node in module_nodes if node.domain)),
    )
    return GraphBatch(
        codebase=codebase.name,
        nodes=(codebase_node, *code_nodes, *externals),
        edges=(*defines, *imports),
        stats=stats,
    )


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
