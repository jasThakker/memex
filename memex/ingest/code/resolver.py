"""Turn parsed references into edges between nodes. Phase 2 covers IMPORTS.

Import rules:
- `import a.b` points at module `a.b` if it is in the codebase, else at External `a.b`.
- `from m import x` points at `m.x` if that is a module, class or function in the codebase.
  Otherwise, if `m` is in the codebase and binds `x` by importing it (directly or through a
  star import), that binding is followed, up to MAX_REEXPORT_HOPS times. If nothing is found,
  the edge points at module `m`, or at External `m.x` when `m` is outside the codebase.
- `from m import *` gives one edge to `m` (or External `m`) with names ("*",).
- Relative imports resolve against the importing module's package; one that climbs above the
  top-level package is dropped.
- Names from one module that reach the same target share one edge.
"""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import PurePosixPath

from memex.graph.model import Edge, ExternalNode, code_id, external_id
from memex.ingest.code.parser import ParsedModule, RawImport

MAX_REEXPORT_HOPS = 5


def link_imports(
    codebase: str, modules: Sequence[ParsedModule]
) -> tuple[list[Edge], list[ExternalNode]]:
    """IMPORTS edges for every module, plus the External nodes they point at."""
    index = _Index(modules)
    edges: dict[tuple[str, str], Edge] = {}
    externals: dict[str, ExternalNode] = {}
    for module in modules:
        source = code_id(codebase, module.source.qualname)
        for raw in module.imports:
            resolved = index.resolve(module, raw)
            if resolved is None:
                continue
            dotted, is_external = resolved
            if is_external:
                target = external_id(codebase, dotted)
                externals.setdefault(
                    dotted, ExternalNode(id=target, codebase=codebase, name=dotted)
                )
            else:
                target = code_id(codebase, dotted)
            names = () if raw.name is None else (raw.name,)
            previous = edges.get((source, target))
            if previous is None:
                edges[(source, target)] = Edge(
                    kind="IMPORTS", source=source, target=target, names=names, line=raw.line
                )
            else:
                merged = previous.names + tuple(n for n in names if n not in previous.names)
                edges[(source, target)] = replace(previous, names=merged)
    return list(edges.values()), list(externals.values())


class _Index:
    """Lookups over one codebase's parsed modules, by dotted qualname."""

    def __init__(self, modules: Sequence[ParsedModule]) -> None:
        self.modules = {module.source.qualname: module for module in modules}
        self.symbols = {node.qualname for module in modules for node in module.nodes}

    def resolve(self, module: ParsedModule, raw: RawImport) -> tuple[str, bool] | None:
        """(dotted target, is_external) for one import, or None if it cannot be placed."""
        base = _absolute(module, raw)
        if base is None:
            return None
        if raw.name is None or raw.name == "*":
            return base, base not in self.modules
        found = self.find(base, raw.name, hops=0)
        if found is not None:
            return found, False
        if base in self.modules:
            return base, False
        return f"{base}.{raw.name}", True

    def find(self, module: str, name: str, hops: int) -> str | None:
        """Qualname of the module, class or function that `name` in `module` refers to."""
        candidate = f"{module}.{name}"
        if candidate in self.symbols:
            return candidate
        parsed = self.modules.get(module)
        if parsed is None or hops >= MAX_REEXPORT_HOPS:
            return None
        for raw in parsed.imports:  # an explicit binding of `name` wins over star imports
            if raw.name == "*" or (raw.alias or raw.name) != name:
                continue
            base = _absolute(parsed, raw)
            if base is None:
                return None
            if raw.name is None:  # import a.b as name
                return base if base in self.modules else None
            return self.find(base, raw.name, hops + 1)
        for raw in parsed.imports:
            if raw.name != "*":
                continue
            base = _absolute(parsed, raw)
            found = None if base is None else self.find(base, name, hops + 1)
            if found is not None:
                return found
        return None


def _absolute(module: ParsedModule, raw: RawImport) -> str | None:
    """The absolute dotted module an import refers to, or None if it climbs too high."""
    if raw.level == 0:
        return raw.module
    package = module.source.qualname.split(".")
    if PurePosixPath(module.source.path).name != "__init__.py":
        package = package[:-1]
    keep = len(package) - (raw.level - 1)
    if keep <= 0:
        return None
    return ".".join([*package[:keep], *([raw.module] if raw.module else [])])
