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
- `self.m()`, `cls.m()`, `cls()`, `super().m()`, `super(C, self).m()`, `C.m()` and `C(...).m()`
  where `C` is a class in the codebase: the method on that class or its bases, depth first:
  `exact`. `super()` inside a class nested in a method, or with no class node, is unresolved.
- `self.a.m()` and `self.a.b.m()` where each attribute is typed by the class or its bases:
  a property or cached_property's return annotation, or in `__init__`, `self.a: C = ...`,
  `self.a = C(...)` or `self.a = p` with `p: C`, every assignment agreeing on one class
  (`SymbolTable.attribute_class`). The method on that class or its bases: `exact`. If it has
  none, the rules below apply.
- `alias.f()` or `alias.sub.f()` where `alias` is an imported module in the codebase: `exact`.
- Otherwise, a name that only one function in the codebase has: `inferred`. Never for dunder
  names, names of builtin type methods (`add`, `pop`, `encode`, `get`, ...), `super()` calls,
  or a bare name bound inside the function or by the module (a parameter, variable, nested def,
  module-level assignment, or an import the resolver cannot place).
- Calling a class runs its `__init__`, found through its bases. A class with no `__init__` in
  the codebase gives no edge and is not unresolved.
- A call rooted at a builtin, a literal or a name from outside the codebase gives no edge and
  is not unresolved. Every other call without an edge is counted as unresolved.
- One edge per caller and callee: the first call site's line, `exact` over `inferred`.
"""

import ast
import builtins
from collections.abc import Sequence
from dataclasses import dataclass, replace
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


# Resolve-stage linker: turns each RawImport into an IMPORTS edge to the real target (following
# re-exports), or to an External node for outside names.
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


# Resolve-stage linker: an INHERITS edge from each class to each base class as written; outside
# bases become External nodes.
def link_inherits(codebase: str, symbols: SymbolTable) -> tuple[list[Edge], list[ExternalNode]]:
    """INHERITS edges for every class, plus the External nodes they point at."""
    edges: list[Edge] = []
    externals: dict[str, ExternalNode] = {}
    for module in symbols.modules.values():
        for node in module.nodes:
            definition = module.definitions.get(node.qualname)
            if not isinstance(node, ClassNode) or not isinstance(definition, ast.ClassDef):
                continue
            for position, resolved in enumerate(symbols.written_bases(node.qualname)):
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


# Resolve-stage linker: for every function, finds each call site and asks _CallResolver.resolve;
# makes one CALLS edge per (caller, callee), exact or inferred, and counts the unresolved calls.
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
            for site in _call_sites(definition, resolver.receiver):
                call = site.call
                outcome = resolver.resolve(site)
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


# Resolve-stage linker (ADR-003): a USES edge where code names a function or class as a value
# without calling it, e.g. Depends(get_current_user).
def link_uses(codebase: str, symbols: SymbolTable) -> list[Edge]:
    """USES edges (ADR-003): a function or class naming a codebase function or class as a
    value, in a function's body and own parameter defaults, or in a class body's values.

    A name that is the callee of a call with a CALLS edge does not count; annotations,
    strings and a function's own decorators are never read. One edge per pair, at its first
    line; a symbol naming itself gives none.
    """
    first_line: dict[tuple[str, str], int] = {}
    for module in symbols.modules.values():
        for node in module.nodes:
            definition = module.definitions.get(node.qualname)
            if isinstance(node, FunctionNode) and isinstance(
                definition, ast.FunctionDef | ast.AsyncFunctionDef
            ):
                resolver = _CallResolver(symbols, module, node, definition)
                found = _function_values(definition, resolver)
            elif isinstance(node, ClassNode) and isinstance(definition, ast.ClassDef):
                resolver = _CallResolver(symbols, module, None, None)
                found = _class_values(definition, resolver)
            else:
                continue
            for target, line in found:
                if target == node.qualname:
                    continue
                key = (node.id, code_id(codebase, target))
                first_line[key] = min(line, first_line.get(key, line))
    return [
        Edge(kind="USES", source=source, target=target, line=line)
        for (source, target), line in first_line.items()
    ]


# (node, names bound around it, receiver in scope, whether a call here can get a CALLS edge)
_ValueVisit = tuple[ast.AST, frozenset[str], bool, bool]


# Helper for link_uses: every value reference in a function's body and its own parameter defaults.
def _function_values(
    definition: ast.FunctionDef | ast.AsyncFunctionDef, resolver: _CallResolver
) -> list[tuple[str, int]]:
    """(target, line) of every value reference in a function's body and own defaults."""
    defaults = [
        *definition.args.defaults,
        *(d for d in definition.args.kw_defaults if d is not None),
    ]
    stack: list[_ValueVisit] = [(d, frozenset(), False, False) for d in defaults]
    outer = _scope_names(definition)
    stack.extend((statement, outer, True, True) for statement in definition.body)
    return _values(stack, resolver)


# Helper for link_uses: every value reference in a class body (methods left out).
def _class_values(definition: ast.ClassDef, resolver: _CallResolver) -> list[tuple[str, int]]:
    """(target, line) of every value reference in a class body, nested defs left out."""
    stack: list[_ValueVisit] = [
        (statement, frozenset(), False, False)
        for statement in definition.body
        if not isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]
    return _values(stack, resolver)


# Helper for link_uses: walks expressions with a stack, finds names read as values and resolves each
# with value_target. Skips annotations.
def _values(stack: list[_ValueVisit], resolver: _CallResolver) -> list[tuple[str, int]]:
    """Walks expressions for read names and dotted names, skipping annotations. Iterative."""
    found: list[tuple[str, int]] = []
    while stack:
        node, names, receiver_in_scope, linked = stack.pop()
        match node:
            case ast.Name(ctx=ast.Load()) | ast.Attribute(ctx=ast.Load()):
                root: ast.expr = node
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name):
                    target = resolver.value_target(node, names, receiver_in_scope)
                    if target is not None:
                        found.append((target, node.lineno))
                else:  # `f().x`, `a[0].x`: the root holds its own names
                    stack.append((root, names, receiver_in_scope, linked))
                continue
            case ast.Call() if linked:
                site = _CallSite(node, names, receiver_in_scope)
                calls = isinstance(resolver.resolve(site), tuple)
                if not (calls and isinstance(node.func, ast.Name | ast.Attribute)):
                    stack.append((node.func, names, receiver_in_scope, linked))
                elif isinstance(node.func, ast.Attribute):
                    root = node.func.value
                    while isinstance(root, ast.Attribute):
                        root = root.value
                    if not isinstance(root, ast.Name):
                        stack.append((root, names, receiver_in_scope, linked))
                children = [*node.args, *(keyword.value for keyword in node.keywords)]
                stack.extend((child, names, receiver_in_scope, linked) for child in children)
                continue
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.Lambda():
                outside = [
                    *getattr(node, "decorator_list", []),
                    *node.args.defaults,
                    *(d for d in node.args.kw_defaults if d is not None),
                ]
                stack.extend((child, names, receiver_in_scope, linked) for child in outside)
                inner = names | _scope_names(node)
                rebinds = resolver.receiver is not None and resolver.receiver in _parameters(node)
                body = node.body if isinstance(node.body, list) else [node.body]
                inside = receiver_in_scope and not rebinds
                stack.extend((child, inner, inside, linked) for child in body)
                continue
            case ast.ClassDef():
                children = [*node.decorator_list, *node.bases, *node.body]
                stack.extend((child, names, receiver_in_scope, linked) for child in children)
                continue
            case ast.AnnAssign():
                if node.value is not None:
                    stack.append((node.value, names, receiver_in_scope, linked))
                continue
            case ast.arg() | ast.Constant():
                continue
        stack.extend(
            (child, names, receiver_in_scope, linked) for child in ast.iter_child_nodes(node)
        )
    return found


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

    # Sets up resolving for ONE function: its class (for self.m()), the name of self/cls, whether it
    # is a classmethod, and imports done inside it.
    def __init__(
        self,
        symbols: SymbolTable,
        module: ParsedModule,
        function: FunctionNode | None,
        definition: ast.FunctionDef | ast.AsyncFunctionDef | None,
    ) -> None:
        """Without a function, names are seen from module scope (a class body)."""
        self.symbols = symbols
        self.module = module
        self.locals: frozenset[str] = frozenset()
        self.active_receiver: str | None = None
        if function is None or definition is None:
            self.cls: str | None = None
            self.receiver: str | None = None
            self.is_classmethod = False
            self.imports: dict[str | None, RawImport] = {}
            return
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

    # Used by link_uses: which function or class a name like `helper` or `self.service.run` refers
    # to, or None.
    def value_target(
        self, expr: ast.Name | ast.Attribute, names: frozenset[str], receiver_in_scope: bool
    ) -> str | None:
        """The function or class a read name or dotted name refers to, by its longest leading
        part that resolves exactly (ADR-003), or None."""
        self.locals = names
        self.active_receiver = self.receiver if receiver_in_scope else None
        parts: list[str] = []
        root: ast.expr = expr
        while isinstance(root, ast.Attribute):
            parts.insert(0, root.attr)
            root = root.value
        if not isinstance(root, ast.Name):
            return None
        if root.id == self.active_receiver and self.cls is not None:  # self.m, self.a.m
            owner: str | None = self.cls
            for part in parts:
                if owner is None:
                    return None
                method = self.symbols.method(owner, part)
                if method is not None:
                    return method
                owner = self.symbols.attribute_class(owner, part)
            return None
        head = self._head(root.id)
        if not isinstance(head, tuple) or head[1]:
            return None
        dotted, target = head[0], None
        for part in [None, *parts]:
            if part is not None:
                found = self.symbols.find(dotted, part, hops=0)
                if found is None:
                    break
                dotted = found
            if dotted in self.symbols.functions or dotted in self.symbols.classes:
                target = dotted
        return target

    # The call-resolution entry point, one call site at a time: bare name -> _resolve_name_call,
    # attribute -> _resolve_attribute_call. Returns (target, exact|inferred), EXTERNAL or
    # UNRESOLVED.
    def resolve(self, site: _CallSite) -> _Outcome:
        """The outcome of one call site, seen from the scope it sits in."""
        self.locals = site.locals
        self.active_receiver = self.receiver if site.receiver_in_scope else None
        func = site.call.func
        if isinstance(func, ast.Name):
            return self._resolve_name_call(func.id)
        if isinstance(func, ast.Attribute):
            return self._resolve_attribute_call(func)
        return _EXTERNAL if self._root_is_external(func) else _UNRESOLVED

    # Helper for resolve: a bare call `f()`. Defined or imported in the module -> exact; a local
    # variable -> unresolved; otherwise try _inferred (unique name).
    def _resolve_name_call(self, name: str) -> _Outcome:
        if name == self.active_receiver and self.is_classmethod and self.cls is not None:
            return self._target(self.cls)  # cls(...)
        head = self._head(name)
        if head == _LOCAL:
            return _UNRESOLVED
        if head is None:
            if name in self.imports or name in self.symbols.module_names(self.module):
                return _UNRESOLVED  # bound, but not to anything the resolver can place
            return self._inferred(name)
        dotted, is_external = head
        return _EXTERNAL if is_external else self._target(dotted)

    # Helper for resolve: a call `x.m()`. Works out the class of x (self, super(), a typed
    # self.attr, C(...), a class name, a module), then finds m on it -> exact; else external, or
    # _inferred.
    def _resolve_attribute_call(self, func: ast.Attribute) -> _Outcome:
        receiver, name = func.value, func.attr
        cls: str | None = None
        if self._is_super(receiver):
            return self._resolve_super(receiver, name)
        if isinstance(receiver, ast.Name) and receiver.id == self.active_receiver:
            cls = self.cls
        elif (typed := self._attribute_class(receiver)) is not None:  # self.a.m(), self.a.b.m()
            cls = typed
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

    # Helper for _resolve_attribute_call: super().m() looks m up on the bases of the method's class.
    def _resolve_super(self, call: ast.Call, name: str) -> _Outcome:
        """`super().m()` or `super(C, self).m()`: the bases of the method's class (or of C).

        Inside a nested class, or outside any class node, the class is unknown: unresolved.
        """
        if self.cls is None or self.active_receiver is None:
            return _UNRESOLVED
        start = self.cls
        if call.args:
            explicit = self._dotted(call.args[0])
            if explicit is None or explicit[1] or explicit[0] not in self.symbols.classes:
                return _UNRESOLVED
            start = explicit[0]
        for base in self.symbols.bases(start):
            found = self.symbols.method(base, name)
            if found is not None:
                return found, "exact"
        if self.symbols.has_outside_base(start) or hasattr(object, name):
            return _EXTERNAL  # the method comes from a base outside the codebase
        return _UNRESOLVED

    # Helper (Phase 9 typed attributes): the class of self.a or self.a.b, from annotations,
    # properties or __init__ assignments.
    def _attribute_class(self, expr: ast.expr) -> str | None:
        """The class of `self.a` or `self.a.b`, one typed attribute per step, or None."""
        if isinstance(expr, ast.Name):
            is_instance = expr.id == self.active_receiver and not self.is_classmethod
            return self.cls if is_instance else None
        if isinstance(expr, ast.Attribute):
            owner = self._attribute_class(expr.value)
            return None if owner is None else self.symbols.attribute_class(owner, expr.attr)
        return None

    # Helper: what a bare name means inside this function: a local variable, an in-codebase or
    # outside dotted name, or unknown.
    def _head(self, name: str) -> tuple[str, bool] | str | None:
        """What a bare name in this function refers to: (dotted, is_external), _LOCAL or None."""
        if name in self.imports:
            return self.symbols.resolve_binding(self.module, self.imports[name])
        if name in self.locals:
            return _LOCAL
        return self.symbols.resolve_name(self.module, name)

    # Helper: the full dotted name of `a` or `a.b.c` as the module binds it, plus whether it is
    # outside the codebase.
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

    # Helper: True if a call chain starts at a literal, a builtin or an outside import ('x'.join(),
    # json.dumps) -> ignored, not unresolved.
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
        if isinstance(expr, ast.Name) and expr.id not in (self.active_receiver, "super"):
            head = self._head(expr.id)
            return isinstance(head, tuple) and head[1]
        return False

    # Helper: the function a call to an in-codebase name runs; calling a class means its __init__.
    def _target(self, dotted: str) -> _Outcome:
        """The function a call to an in-codebase name runs."""
        if dotted in self.symbols.functions:
            return dotted, "exact"
        if dotted in self.symbols.classes:
            init = self.symbols.method(dotted, "__init__")
            return _NOT_A_FUNCTION if init is None else (init, "exact")
        return _UNRESOLVED

    # Rule 5, the fallback: if exactly ONE function in the codebase has this name, return it as
    # 'inferred'; otherwise unresolved. Never guesses.
    def _inferred(self, name: str) -> _Outcome:
        candidates = self.symbols.functions_by_name.get(name, [])
        is_dunder = name.startswith("__") and name.endswith("__")
        if len(candidates) == 1 and not is_dunder and name not in _BUILTIN_METHOD_NAMES:
            return candidates[0], "inferred"
        return _UNRESOLVED

    # Helper: True if an expression is a `super(...)` call.
    @staticmethod
    def _is_super(expr: ast.expr) -> bool:
        return (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Name)
            and expr.func.id == "super"
        )


@dataclass(frozen=True)
class _CallSite:
    """One call, with the names bound in the scopes around it."""

    call: ast.Call
    locals: frozenset[str]  # parameters, variables and nested defs of every enclosing scope
    receiver_in_scope: bool  # False inside a nested def or lambda that rebinds `self`/`cls`


_Scope = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda


# Helper for link_calls: every call inside a function body (nested defs and lambdas included), each
# with the local names in scope. Iterative.
def _call_sites(
    definition: ast.FunctionDef | ast.AsyncFunctionDef, receiver: str | None
) -> list[_CallSite]:
    """Every call in a function body, nested defs and lambdas included, in source order.

    Decorators and defaults of a nested def are evaluated in the scope around it. Iterative,
    so deeply nested expressions do not recurse.
    """
    found: list[_CallSite] = []
    outer = _scope_names(definition)
    stack: list[tuple[ast.AST, frozenset[str], bool]] = [
        (statement, outer, True) for statement in definition.body
    ]
    while stack:
        node, names, receiver_in_scope = stack.pop()
        if isinstance(node, ast.Call):
            found.append(_CallSite(node, names, receiver_in_scope))
        if isinstance(node, _Scope):
            evaluated_outside = [
                *getattr(node, "decorator_list", []),
                *node.args.defaults,
                *(default for default in node.args.kw_defaults if default is not None),
            ]
            stack.extend((child, names, receiver_in_scope) for child in evaluated_outside)
            inner = names | _scope_names(node)
            rebinds = receiver is not None and receiver in _parameters(node)
            body = node.body if isinstance(node.body, list) else [node.body]
            stack.extend((child, inner, receiver_in_scope and not rebinds) for child in body)
            continue
        stack.extend((child, names, receiver_in_scope) for child in ast.iter_child_nodes(node))
    return sorted(found, key=lambda site: (site.call.lineno, site.call.col_offset))


# Helper: the parameter names of a function or lambda.
def _parameters(scope: _Scope) -> set[str]:
    arguments = scope.args
    return {
        arg.arg
        for arg in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            *(a for a in (arguments.vararg, arguments.kwarg) if a is not None),
        )
    }


# Helper: names a function binds itself (parameters, assignments, nested defs). Used to tell a local
# variable from a module-level name.
def _scope_names(scope: _Scope) -> frozenset[str]:
    """Names one function or lambda binds itself: parameters, assigned names, nested def and
    class names, except-as names. Names bound only inside nested scopes are not included."""
    names = _parameters(scope)
    stack: list[ast.AST] = list(scope.body) if isinstance(scope.body, list) else [scope.body]
    while stack:
        node = stack.pop()
        match node:
            case ast.Name(ctx=ast.Store()):
                names.add(node.id)
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names.add(node.name)
                continue  # its body is its own scope
            case ast.Lambda():
                continue
            case ast.ExceptHandler(name=str()):
                names.add(node.name)
        stack.extend(ast.iter_child_nodes(node))
    return frozenset(names)


# Helper for _CallResolver.__init__: a decorator's name, to spot @staticmethod and @classmethod.
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

    # Builds the lookup tables once from all parsed modules: every qualname, classes, functions,
    # functions_by_name, and so on. Shared by the resolver and the extractors.
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
        self.classes_by_name: dict[str, list[str]] = {}
        for qualname in sorted(self.classes):
            self.classes_by_name.setdefault(qualname.rsplit(".", 1)[-1], []).append(qualname)
        self.packages = {qualname.split(".")[0] for qualname in self.modules}
        self.nodes = {node.qualname: node for module in modules for node in module.nodes}
        self._module_of = {node.qualname: module for module in modules for node in module.nodes}
        self._written_bases: dict[str, list[tuple[str, bool] | None]] = {}
        self._module_names: dict[str, frozenset[str]] = {}
        self._class_attributes: dict[str, dict[str, str]] = {}
        self._typed_attributes: dict[str, dict[str, str | None]] = {}

    # Lookup: the parsed module a qualname comes from.
    def module_of(self, qualname: str) -> ParsedModule:
        """The parsed module a module, class or function node comes from."""
        return self._module_of[qualname]

    # Lookup: every name a module binds at top level (definitions, assignments, imports). Cached.
    def module_names(self, module: ParsedModule) -> frozenset[str]:
        """Every name a module binds at module level: definitions, assignments, imports."""
        qualname = module.source.qualname
        if qualname not in self._module_names:
            names = {name for raw in module.imports if raw.module_level for name in [binds(raw)]}
            stack: list[ast.AST] = list(module.tree.body)
            while stack:
                node = stack.pop()
                match node:
                    case ast.Name(ctx=ast.Store()):
                        names.add(node.id)
                    case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                        names.add(node.name)
                        continue  # its body is its own scope
                    case ast.Lambda():
                        continue
                    case ast.ExceptHandler(name=str()):
                        names.add(node.name)
                stack.extend(ast.iter_child_nodes(node))
            self._module_names[qualname] = frozenset(name for name in names if name)
        return self._module_names[qualname]

    # Lookup: string constants assigned in a class body, e.g. __tablename__ = 'users'. Used by the
    # sqlalchemy extractor.
    def class_attributes(self, cls: str) -> dict[str, str]:
        """String literals assigned directly in a class body: `__tablename__ = "users"`."""
        if cls not in self._class_attributes:
            definition = self._module_of[cls].definitions.get(cls)
            found: dict[str, str] = {}
            body = definition.body if isinstance(definition, ast.ClassDef) else []
            for statement in body:
                match statement:
                    case ast.Assign(
                        targets=[ast.Name(id=name)], value=ast.Constant(value=str() as value)
                    ):
                        found.setdefault(name, value)
                    case ast.AnnAssign(
                        target=ast.Name(id=name), value=ast.Constant(value=str() as value)
                    ):
                        found.setdefault(name, value)
            self._class_attributes[cls] = found
        return self._class_attributes[cls]

    # Lookup: classes whose body assigns this string to this attribute (which class has
    # __tablename__ 'users'?). Used by the extractor.
    def by_class_attribute(self, attribute: str, value: str) -> list[str]:
        """Classes whose body assigns the string `value` to `attribute`, sorted."""
        return sorted(
            cls for cls in self.classes if self.class_attributes(cls).get(attribute) == value
        )

    # Lookup: each base of a class as written, resolved to a dotted name (and whether it is outside
    # the codebase).
    def written_bases(self, cls: str) -> list[tuple[str, bool] | None]:
        """(dotted, is_external) of each base as written, or None where it cannot be placed.

        Bases are evaluated before the class binds its own name, so in
        `from x import Base` / `class Base(Base)` the base is the imported one.
        """
        if cls not in self._written_bases:
            module = self._module_of[cls]
            definition = module.definitions.get(cls)
            found: list[tuple[str, bool] | None] = []
            for base in definition.bases if isinstance(definition, ast.ClassDef) else []:
                resolved = self.resolve_expression(module, base)
                named = base.value if isinstance(base, ast.Subscript) else base
                if resolved == (cls, False) and isinstance(named, ast.Name):
                    resolved = self._bound_before(module, named.id, self.definition_lines[cls])
                found.append(resolved)
            self._written_bases[cls] = found
        return self._written_bases[cls]

    # Lookup: the in-codebase base classes of a class.
    def bases(self, cls: str) -> list[str]:
        """In-codebase base classes of a class, in the order written."""
        return [
            dotted
            for dotted, is_external in filter(None, self.written_bases(cls))
            if not is_external and dotted in self.classes and dotted != cls
        ]

    # Lookup: a class and all its in-codebase ancestors, each once (safe with cycles).
    def ancestors(self, cls: str) -> list[str]:
        """The class and every in-codebase class it inherits from, each once."""
        seen: dict[str, None] = {}
        stack = [cls]
        while stack:
            current = stack.pop()
            if current not in seen:
                seen[current] = None
                stack.extend(reversed(self.bases(current)))
        return list(seen)

    # Lookup: True if the class or an ancestor inherits from something outside the codebase (so a
    # missing method may live there).
    def has_outside_base(self, cls: str) -> bool:
        """True if the class or an in-codebase ancestor has a base outside the codebase (or
        one that cannot be placed)."""
        return any(
            resolved is None or resolved[1] or resolved[0] not in self.classes
            for ancestor in self.ancestors(cls)
            for resolved in self.written_bases(ancestor)
        )

    # Lookup: the method `name` on a class or, depth first, its bases. Used for self.m(),
    # super().m() and typed attribute calls.
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

    # Lookup (rule 3): the class of instance attribute self.<name>, from the class or its bases.
    # Used by _attribute_class.
    def attribute_class(self, cls: str, name: str) -> str | None:
        """The codebase class of instance attribute `name`, from the first of the class and
        its bases (depth first) that types it, or None (DESIGN.md section 9, rule 3)."""
        for owner in self.ancestors(cls):
            typed = self._attributes_typed_by(owner)
            if name in typed:
                return typed[name]
        return None

    # Helper for attribute_class: the attributes one class types, from property return annotations
    # and __init__ assignments.
    def _attributes_typed_by(self, cls: str) -> dict[str, str | None]:
        """Attributes one class types, each with its class, or None when it is not exactly one.

        A property or cached_property gives its return annotation. In `__init__`, every
        assignment to `self.a` counts: `self.a: C = ...`, `self.a = C(...)`, and `self.a = p`
        for a parameter annotated `p: C`; any other assignment leaves `a` untyped.
        """
        if cls in self._typed_attributes:
            return self._typed_attributes[cls]
        module = self.module_of(cls)
        found: dict[str, set[str | None]] = {}
        for qualname, definition in module.definitions.items():
            if qualname.rsplit(".", 1)[0] != cls or not isinstance(
                definition, ast.FunctionDef | ast.AsyncFunctionDef
            ):
                continue
            decorators = {_decorator_name(d) for d in definition.decorator_list}
            if definition.name == "__init__":
                self._init_attributes(module, definition, found)
            elif decorators & {"property", "cached_property"}:
                kind = self._annotation_class(module, definition.returns)
                found.setdefault(definition.name, set()).add(kind)
        typed = {
            name: next(iter(kinds)) if len(kinds) == 1 else None for name, kinds in found.items()
        }
        self._typed_attributes[cls] = typed
        return typed

    # Helper for _attributes_typed_by: reads `self.a = ...` assignments in __init__ and records each
    # attribute's class (None if unclear).
    def _init_attributes(
        self,
        module: ParsedModule,
        init: ast.FunctionDef | ast.AsyncFunctionDef,
        found: dict[str, set[str | None]],
    ) -> None:
        """Adds the class of each `self.a` assignment in `__init__` (None if unknown)."""
        positional = [*init.args.posonlyargs, *init.args.args]
        if not positional:
            return
        receiver = positional[0].arg
        annotations = {
            arg.arg: arg.annotation
            for arg in [*positional[1:], *init.args.kwonlyargs]
            if arg.annotation is not None
        }

        # Inner helper: records one self.a assignment; two assignments that disagree on the class
        # make it None.
        def record(target: ast.expr, value: ast.expr | None, annotation: ast.expr | None) -> None:
            if isinstance(target, ast.Tuple | ast.List):
                for element in target.elts:
                    record(element, None, None)
                return
            if not (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == receiver
            ):
                return
            kind = None
            if annotation is not None:
                kind = self._annotation_class(module, annotation)
            elif isinstance(value, ast.Call):
                kind = self._annotation_class(module, value.func)
            elif isinstance(value, ast.Name) and value.id in annotations:
                kind = self._annotation_class(module, annotations[value.id])
            found.setdefault(target.attr, set()).add(kind)

        stack: list[ast.AST] = list(init.body)
        while stack:
            node = stack.pop()
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
                continue  # another scope: its `self` is not this one
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    record(target, node.value, None)
            elif isinstance(node, ast.AnnAssign):
                record(node.target, node.value, node.annotation)
            stack.extend(ast.iter_child_nodes(node))

    # Helper: the codebase class an annotation names (Repo, pkg.Repo or the string 'Repo'), or None.
    def _annotation_class(self, module: ParsedModule, expr: ast.expr | None) -> str | None:
        """The codebase class a name, dotted name or string annotation refers to, or None."""
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            try:
                expr = ast.parse(expr.value, mode="eval").body
            except SyntaxError:
                return None
        if expr is None:
            return None
        resolved = self.resolve_expression(module, expr)
        if resolved is None or resolved[1] or resolved[0] not in self.classes:
            return None
        return resolved[0]

    # Used by link_imports: where one import points, as (dotted target, is_external).
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

    # Core lookup: what `name` inside module `m` really is, following imports and star re-exports up
    # to a hop limit.
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

    # Lookup: what a bare name means at module level, as (dotted target, is_external).
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

    # Lookup: what a name, dotted name or subscript (Generic[T] -> Generic) refers to. Used for
    # bases and by the extractor.
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

    # Helper: the target of the name one import binds.
    def resolve_binding(
        self, module: ParsedModule, raw: RawImport, hops: int = 0
    ) -> tuple[str, bool] | None:
        """(dotted target, is_external) of the name one import binds, or None.

        A name that a codebase module only re-exports from outside (`from json import dumps`
        in `pkg/compat.py`) is followed to the outside name, up to MAX_REEXPORT_HOPS times.
        """
        base = _absolute(module, raw)
        if base is None:
            return None
        if raw.name is None:  # `import a.b as c` binds a.b; `import a.b` binds a
            return self._outside(base if raw.alias else base.split(".")[0])
        found = self.find(base, raw.name, hops=0)
        if found is not None:
            return found, False
        source = self.modules.get(base)
        if source is not None and hops < MAX_REEXPORT_HOPS:
            for inner in reversed(source.imports):
                if inner.module_level and binds(inner) == raw.name:
                    return self.resolve_binding(source, inner, hops + 1)
        return self._outside(f"{base}.{raw.name}")

    # Helper: what a module-level import binds a name to before a given line (a later import of the
    # same name wins after it).
    def _bound_before(self, module: ParsedModule, name: str, line: int) -> tuple[str, bool] | None:
        """What a module-level import binds `name` to before `line`, or None."""
        for raw in reversed(module.imports):
            if raw.module_level and raw.line < line and binds(raw) == name:
                return self.resolve_binding(module, raw)
        return None

    # Helper for resolve: a dotted name find() missed: a walked module, an External, or nothing.
    def _outside(self, dotted: str) -> tuple[str, bool] | None:
        """A dotted name not found by `find`: a walked module, External, or nothing."""
        if dotted in self.modules:
            return dotted, False
        if dotted.split(".")[0] in self.packages:
            return None  # inside the codebase but not walked, or not a symbol
        return dotted, True

    # Helper for find: follows one import inside a module to where it leads (one re-export hop).
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


# Helper: the local name an import creates (`import a.b as c` -> 'c'); None for a star import.
def binds(raw: RawImport) -> str | None:
    """The local name an import binds, or None for a star import."""
    if raw.name == "*":
        return None
    if raw.alias is not None:
        return raw.alias
    if raw.name is not None:
        return raw.name
    return None if raw.module is None else raw.module.split(".")[0]


# Helper: turns a relative import (`from ..m import x`) into an absolute module name; None if it
# climbs above the package.
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
