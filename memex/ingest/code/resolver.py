"""Turn parsed references into edges between nodes: IMPORTS, INHERITS and CALLS.

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

Inheritance rules (INHERITS, position is the base's 0-based index as written):
- A base is a name or a dotted attribute (`base.Mixin`, `typing.Protocol`); a subscript uses
  its value (`Generic[T]` gives `Generic`). Keyword arguments such as `metaclass=` are
  ignored, and any other expression gets no edge.
- Names are looked up as the module binds them once it has run (a local class defined after
  an import of the same name wins), then as builtins (External `builtins.X`). `object` is
  skipped.
- An in-codebase target must be a class; one outside the codebase becomes External, with the
  same id an import of it would get.

Call rules (CALLS, DESIGN.md section 9), for call sites inside a function body, nested defs
and lambdas included (not decorators or defaults):
- A bare name defined or imported in the module, or imported inside the function: `exact`.
- `self.m()`, `cls.m()`, `cls()`, `super().m()`, `C.m()` and `C(...).m()` where `C` is a class
  in the codebase: the method on that class or its bases, depth first: `exact`.
- `alias.f()` or `alias.sub.f()` where `alias` is an imported module in the codebase: `exact`.
- Otherwise, a name that only one function in the codebase has: `inferred`. Never for dunder
  names, names of builtin type methods (`add`, `pop`, `encode`, `get`, ...), or a bare name
  bound inside the function (a parameter, variable or nested def).
- Calling a class runs its `__init__`, found through its bases. A class with no `__init__` in
  the codebase gives no edge and is not unresolved.
- A call rooted at a builtin, a literal or a name from outside the codebase gives no edge and
  is not unresolved. Every other call without an edge is counted as unresolved.
- One edge per caller and callee: the first call site's line, `exact` over `inferred`.
"""

import ast
import builtins
from collections.abc import Sequence
from dataclasses import replace
from pathlib import PurePosixPath

from memex.graph.model import (
    ClassNode,
    Confidence,
    Edge,
    ExternalNode,
    FunctionNode,
    code_id,
    external_id,
)
from memex.ingest.code.parser import ParsedModule, RawImport

MAX_REEXPORT_HOPS = 5


def link_imports(
    codebase: str, modules: Sequence[ParsedModule]
) -> tuple[list[Edge], list[ExternalNode]]:
    """IMPORTS edges for every module, plus the External nodes they point at."""
    index = SymbolTable(modules)
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


def link_inherits(codebase: str, symbols: SymbolTable) -> tuple[list[Edge], list[ExternalNode]]:
    """INHERITS edges for every class, plus the External nodes they point at."""
    edges: list[Edge] = []
    externals: dict[str, ExternalNode] = {}
    for module in symbols.modules.values():
        for node in module.nodes:
            definition = module.definitions.get(node.qualname)
            if not isinstance(node, ClassNode) or not isinstance(definition, ast.ClassDef):
                continue
            for position, base in enumerate(definition.bases):
                resolved = symbols.resolve_expression(module, base)
                if resolved is None or resolved == ("builtins.object", True):
                    continue
                dotted, is_external = resolved
                if is_external:
                    target = external_id(codebase, dotted)
                    externals.setdefault(
                        dotted, ExternalNode(id=target, codebase=codebase, name=dotted)
                    )
                elif dotted in symbols.classes and dotted != node.qualname:
                    target = code_id(codebase, dotted)
                else:
                    continue
                edges.append(
                    Edge(kind="INHERITS", source=node.id, target=target, position=position)
                )
    return edges, list(externals.values())


def link_calls(codebase: str, symbols: SymbolTable) -> tuple[list[Edge], int]:
    """CALLS edges for every function, plus the number of unresolved call sites."""
    edges: dict[tuple[str, str], Edge] = {}
    unresolved = 0
    for module in symbols.modules.values():
        for node in module.nodes:
            definition = module.definitions.get(node.qualname)
            if not isinstance(node, FunctionNode) or not isinstance(
                definition, ast.FunctionDef | ast.AsyncFunctionDef
            ):
                continue
            resolver = _CallResolver(symbols, module, node, definition)
            for call in _calls_in(definition):
                outcome = resolver.resolve(call.func)
                if outcome == _UNRESOLVED:
                    unresolved += 1
                if not isinstance(outcome, tuple):
                    continue
                callee, confidence = outcome
                target = code_id(codebase, callee)
                previous = edges.get((node.id, target))
                if previous is None:
                    edges[(node.id, target)] = Edge(
                        kind="CALLS",
                        source=node.id,
                        target=target,
                        line=call.lineno,
                        confidence=confidence,
                    )
                elif confidence == "exact":
                    edges[(node.id, target)] = replace(previous, confidence="exact")
    return list(edges.values()), unresolved


_EXTERNAL = "external"  # a builtin, a literal, or a name from outside the codebase
_NOT_A_FUNCTION = "not a function"  # constructing a class with no __init__ in the codebase
_UNRESOLVED = "unresolved"
_LOCAL = "local"  # a name bound inside the function: a parameter, variable or nested def
_Outcome = tuple[str, Confidence] | str
# Method names of builtin types (add, pop, encode, get, ...). A call like `x.add()` is far more
# often a set or a session than the one function in the codebase with that name.
_BUILTIN_METHOD_NAMES = frozenset(
    name
    for kind in (str, bytes, bytearray, list, dict, set, frozenset, tuple, int, float, complex)
    for name in dir(kind)
    if not name.startswith("_")
)
_LITERALS = (
    ast.Constant,
    ast.JoinedStr,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


class _CallResolver:
    """Resolves the call sites inside one function (DESIGN.md section 9)."""

    def __init__(
        self,
        symbols: SymbolTable,
        module: ParsedModule,
        function: FunctionNode,
        definition: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self.symbols = symbols
        self.module = module
        parent = function.qualname.rsplit(".", 1)[0]
        self.cls = parent if function.is_method and parent in symbols.classes else None
        decorators = {_decorator_name(d) for d in definition.decorator_list}
        positional = [*definition.args.posonlyargs, *definition.args.args]
        self.receiver = (  # the name of `self` or `cls`
            positional[0].arg
            if self.cls is not None and positional and "staticmethod" not in decorators
            else None
        )
        self.is_classmethod = "classmethod" in decorators
        self.imports = {
            binds(raw): raw
            for raw in module.imports
            if not raw.module_level and function.line <= raw.line <= function.end_line
        }
        self.locals = _local_names(definition)

    def resolve(self, func: ast.expr) -> _Outcome:
        if isinstance(func, ast.Name):
            return self._resolve_name_call(func.id)
        if isinstance(func, ast.Attribute):
            return self._resolve_attribute_call(func)
        return _EXTERNAL if self._root_is_external(func) else _UNRESOLVED

    def _resolve_name_call(self, name: str) -> _Outcome:
        if name == self.receiver and self.is_classmethod and self.cls is not None:
            return self._target(self.cls)  # cls(...)
        head = self._head(name)
        if head == _LOCAL:
            return _UNRESOLVED
        if head is None:
            return self._inferred(name)
        dotted, is_external = head
        return _EXTERNAL if is_external else self._target(dotted)

    def _resolve_attribute_call(self, func: ast.Attribute) -> _Outcome:
        receiver, name = func.value, func.attr
        cls: str | None = None
        if self._is_super(receiver) and self.cls is not None:
            for base in self.symbols.bases(self.cls):
                found = self.symbols.method(base, name)
                if found is not None:
                    return found, "exact"
            return self._inferred(name)
        if isinstance(receiver, ast.Name) and receiver.id == self.receiver:
            cls = self.cls
        elif isinstance(receiver, ast.Call):  # C(...).m()
            constructed = self._dotted(receiver.func)
            if constructed is not None and constructed[0] in self.symbols.classes:
                cls = constructed[0]
        else:
            dotted = self._dotted(receiver)
            if dotted is not None and dotted[1]:
                return _EXTERNAL
            if dotted is not None and dotted[0] in self.symbols.classes:
                cls = dotted[0]
            elif dotted is not None and dotted[0] in self.symbols.modules:
                found_in_module = self.symbols.find(dotted[0], name, hops=0)
                if found_in_module is not None:
                    return self._target(found_in_module)
        if cls is not None:
            found = self.symbols.method(cls, name)
            if found is not None:
                return found, "exact"
        if self._root_is_external(receiver):
            return _EXTERNAL
        return self._inferred(name)

    def _head(self, name: str) -> tuple[str, bool] | str | None:
        """What a bare name in this function refers to: (dotted, is_external), _LOCAL or None."""
        if name in self.imports:
            return self.symbols.resolve_binding(self.module, self.imports[name])
        if name in self.locals:
            return _LOCAL
        return self.symbols.resolve_name(self.module, name)

    def _dotted(self, expr: ast.expr) -> tuple[str, bool] | None:
        """(dotted, is_external) of a name or attribute chain not bound locally, or None."""
        parts: list[str] = []
        while isinstance(expr, ast.Attribute):
            parts.insert(0, expr.attr)
            expr = expr.value
        if not isinstance(expr, ast.Name):
            return None
        head = self._head(expr.id)
        if not isinstance(head, tuple):
            return None
        dotted, is_external = head
        if is_external:
            return ".".join([dotted, *parts]), True
        for part in parts:
            found = self.symbols.find(dotted, part, hops=0)
            if found is None:
                return None
            dotted = found
        return dotted, False

    def _root_is_external(self, expr: ast.expr) -> bool:
        """True if a receiver chain starts at a literal, a builtin or an outside name."""
        while True:
            match expr:
                case ast.Attribute() | ast.Subscript():
                    expr = expr.value
                case ast.Call():
                    expr = expr.func
                case _:
                    break
        if isinstance(expr, _LITERALS):
            return True
        if isinstance(expr, ast.Name) and expr.id not in (self.receiver, "super"):
            head = self._head(expr.id)
            return isinstance(head, tuple) and head[1]
        return False

    def _target(self, dotted: str) -> _Outcome:
        """The function a call to an in-codebase name runs."""
        if dotted in self.symbols.functions:
            return dotted, "exact"
        if dotted in self.symbols.classes:
            init = self.symbols.method(dotted, "__init__")
            return _NOT_A_FUNCTION if init is None else (init, "exact")
        return _UNRESOLVED

    def _inferred(self, name: str) -> _Outcome:
        candidates = self.symbols.functions_by_name.get(name, [])
        is_dunder = name.startswith("__") and name.endswith("__")
        if len(candidates) == 1 and not is_dunder and name not in _BUILTIN_METHOD_NAMES:
            return candidates[0], "inferred"
        return _UNRESOLVED

    @staticmethod
    def _is_super(expr: ast.expr) -> bool:
        return (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Name)
            and expr.func.id == "super"
        )


def _calls_in(definition: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    """Every call in a function body, nested defs included, in source order. Iterative."""
    found: list[ast.Call] = []
    stack: list[ast.AST] = list(definition.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Call):
            found.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return sorted(found, key=lambda call: (call.lineno, call.col_offset))


def _local_names(definition: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Parameters, assigned names, nested defs and except-as names anywhere in a function."""
    arguments = definition.args
    names = {
        arg.arg
        for arg in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            *(a for a in (arguments.vararg, arguments.kwarg) if a is not None),
        )
    }
    stack: list[ast.AST] = list(definition.body)
    while stack:
        node = stack.pop()
        match node:
            case ast.Name(ctx=ast.Store()):
                names.add(node.id)
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names.add(node.name)
            case ast.ExceptHandler(name=str()):
                names.add(node.name)
        stack.extend(ast.iter_child_nodes(node))
    return names


def _decorator_name(decorator: ast.expr) -> str | None:
    if isinstance(decorator, ast.Name):
        return decorator.id
    if isinstance(decorator, ast.Attribute):
        return decorator.attr
    return None


class SymbolTable:
    """Read-only lookups over one codebase's parsed modules, by dotted qualname.

    Shared by the resolver and the framework extractors (DESIGN.md section 6).
    """

    def __init__(self, modules: Sequence[ParsedModule]) -> None:
        self.modules = {module.source.qualname: module for module in modules}
        self.symbols = {node.qualname for module in modules for node in module.nodes}
        self.classes = {
            node.qualname
            for module in modules
            for node in module.nodes
            if isinstance(node, ClassNode)
        }
        self.functions = {
            node.qualname
            for module in modules
            for node in module.nodes
            if isinstance(node, FunctionNode)
        }
        self.functions_by_name: dict[str, list[str]] = {}
        for qualname in sorted(self.functions):
            self.functions_by_name.setdefault(qualname.rsplit(".", 1)[-1], []).append(qualname)
        self.definition_lines = {
            node.qualname: node.line
            for module in modules
            for node in module.nodes
            if isinstance(node, ClassNode | FunctionNode)
        }
        self.packages = {qualname.split(".")[0] for qualname in self.modules}
        self._module_of = {node.qualname: module for module in modules for node in module.nodes}
        self._bases: dict[str, list[str]] = {}

    def bases(self, cls: str) -> list[str]:
        """In-codebase base classes of a class, in the order written."""
        if cls not in self._bases:
            module = self._module_of[cls]
            definition = module.definitions.get(cls)
            found: list[str] = []
            if isinstance(definition, ast.ClassDef):
                for base in definition.bases:
                    resolved = self.resolve_expression(module, base)
                    if resolved is not None and not resolved[1] and resolved[0] in self.classes:
                        found.append(resolved[0])
            self._bases[cls] = [base for base in found if base != cls]
        return self._bases[cls]

    def method(self, cls: str, name: str) -> str | None:
        """The function `name` defined on a class or, depth first in base order, its bases."""
        seen: set[str] = set()
        stack = [cls]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            if f"{current}.{name}" in self.functions:
                return f"{current}.{name}"
            stack.extend(reversed(self.bases(current)))
        return None

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

    def resolve_name(self, module: ParsedModule, name: str) -> tuple[str, bool] | None:
        """(dotted target, is_external) of a bare name as `module` binds it, or None.

        In-codebase bindings first (definitions and imports, through `find`), then an import
        from outside the codebase, then a builtin.
        """
        found = self.find(module.source.qualname, name, hops=0)
        if found is not None:
            return found, False
        for raw in reversed(module.imports):
            if raw.module_level and binds(raw) == name:
                return self.resolve_binding(module, raw)
        if hasattr(builtins, name):
            return f"builtins.{name}", True
        return None

    def resolve_expression(self, module: ParsedModule, expr: ast.expr) -> tuple[str, bool] | None:
        """(dotted target, is_external) of a name, dotted attribute or subscript, or None."""
        if isinstance(expr, ast.Subscript):
            expr = expr.value
        parts: list[str] = []
        while isinstance(expr, ast.Attribute):
            parts.insert(0, expr.attr)
            expr = expr.value
        if not isinstance(expr, ast.Name):
            return None
        resolved = self.resolve_name(module, expr.id)
        if resolved is None:
            return None
        dotted, is_external = resolved
        if is_external:
            return ".".join([dotted, *parts]), True
        for part in parts:
            found = self.find(dotted, part, hops=0)
            if found is None:
                return None
            dotted = found
        return dotted, False

    def resolve_binding(self, module: ParsedModule, raw: RawImport) -> tuple[str, bool] | None:
        """(dotted target, is_external) of the name one import binds, or None."""
        base = _absolute(module, raw)
        if base is None:
            return None
        if raw.name is None:  # `import a.b as c` binds a.b; `import a.b` binds a
            return self._outside(base if raw.alias else base.split(".")[0])
        found = self.find(base, raw.name, hops=0)
        if found is not None:
            return found, False
        return self._outside(f"{base}.{raw.name}")

    def _outside(self, dotted: str) -> tuple[str, bool] | None:
        """A dotted name not found by `find`: a walked module, External, or nothing."""
        if dotted in self.modules:
            return dotted, False
        if dotted.split(".")[0] in self.packages:
            return None  # inside the codebase but not walked, or not a symbol
        return dotted, True

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


def binds(raw: RawImport) -> str | None:
    """The local name an import binds, or None for a star import."""
    if raw.name == "*":
        return None
    if raw.alias is not None:
        return raw.alias
    if raw.name is not None:
        return raw.name
    return None if raw.module is None else raw.module.split(".")[0]


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
