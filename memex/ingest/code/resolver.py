"""Turn parsed references into edges between nodes. Phase 2 covers IMPORTS.

Import rules:
- `import a.b` points at module `a.b` if it is in the codebase, else at External `a.b`.
- `from m import x` points at what `x` is in `m`: first what `m` binds to `x` with its own
  module-level imports (last binding first), then a submodule, class or function `m.x`, then
  a public name from `m`'s star imports. Bindings are followed up to MAX_REEXPORT_HOPS times.
  If nothing is found, the edge points at module `m`, or at External `m.x` when `m` is
  outside the codebase.
- A name under one of the codebase's own top-level packages that was not walked (excluded,
  or compiled) gets no edge and never becomes External.
- `from m import *` gives one edge to `m` (or External `m`) with names ("*",).
- Relative imports resolve against the importing module's package; one that climbs above the
  top-level package is dropped.
- Names from one module that reach the same target share one edge.
"""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import PurePosixPath

from memex.graph.model import ClassNode, Edge, ExternalNode, FunctionNode, code_id, external_id
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
        self.definition_lines = {
            node.qualname: node.line
            for module in modules
            for node in module.nodes
            if isinstance(node, ClassNode | FunctionNode)
        }
        self.packages = {qualname.split(".")[0] for qualname in self.modules}

    def resolve(self, module: ParsedModule, raw: RawImport) -> tuple[str, bool] | None:
        """(dotted target, is_external) for one import, or None if it cannot be placed."""
        base = _absolute(module, raw)
        if base is None:
            return None
        if raw.name is not None and raw.name != "*":
            found = self.find(base, raw.name, hops=0)
            if found is not None:
                return found, False
        if base == module.source.qualname:
            return None  # a package importing an unwalked submodule of itself
        if base in self.modules:
            return base, False
        if base.split(".")[0] in self.packages:
            return None  # inside the codebase but not walked (excluded or compiled)
        if raw.name is None or raw.name == "*":
            return base, True
        return f"{base}.{raw.name}", True

    def find(self, module: str, name: str, hops: int) -> str | None:
        """Qualname of the module, class or function that `name` in `module` refers to.

        Order: the module's own imports of `name` (last one first, as Python keeps the last
        binding; an import above a `def` or `class` of the same name does not count), then a
        submodule, class or function `module.name`, then star imports.
        """
        parsed = self.modules.get(module)
        can_follow = parsed is not None and hops < MAX_REEXPORT_HOPS
        candidate = f"{module}.{name}"
        defined_at = self.definition_lines.get(candidate, 0)
        if parsed is not None and can_follow:
            for raw in reversed(parsed.imports):
                if raw.line < defined_at:
                    break  # the definition comes later and wins
                if raw.module_level and raw.name != "*" and (raw.alias or raw.name) == name:
                    found = self._follow(parsed, raw, hops)
                    if found is not None:
                        return found
        if candidate in self.symbols:
            return candidate
        if parsed is not None and can_follow and not name.startswith("_"):
            for raw in parsed.imports:
                if raw.module_level and raw.name == "*":
                    base = _absolute(parsed, raw)
                    found = None if base is None else self.find(base, name, hops + 1)
                    if found is not None:
                        return found
        return None

    def _follow(self, parsed: ParsedModule, raw: RawImport, hops: int) -> str | None:
        """Where one binding import inside `parsed` leads, or None."""
        base = _absolute(parsed, raw)
        if base is None:
            return None
        if raw.name is None:  # import a.b as name
            return base if base in self.modules else None
        if base == parsed.source.qualname:  # `from . import x` in a package: the submodule
            submodule = f"{base}.{raw.name}"
            return submodule if submodule in self.modules else None
        return self.find(base, raw.name, hops + 1)


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
