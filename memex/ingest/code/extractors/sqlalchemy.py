"""SQLAlchemy models: REFERENCES edges from foreign keys and relationships, and `tablename`.

In an assignment directly in a class body (`user_id = mapped_column(ForeignKey("users.id"))`,
`user = relationship("User")`), with the call resolving to a name under `sqlalchemy`:
- `ForeignKey("table.column")` (or `"schema.table.column"`, or `ForeignKey(Model.id)`) gives
  kind `foreign_key` to the one class whose `__tablename__` is that table.
- `relationship(Model)`, `relationship("Model")`, `relationship("pkg.mod.Model")` or
  `relationship(lambda: Model)` gives kind `relationship`. A string is looked up, as SQLAlchemy
  does, among mapped classes only: as the module binds it, then as a dotted class name, then
  as a mapped class name unique in the codebase. A class is mapped if it or an in-codebase
  ancestor has a `__tablename__` or a base under `sqlalchemy`.
- `attr` is the assigned attribute, `line` the call's line. A target that cannot be placed, or
  is ambiguous, gives no edge.
A class whose body assigns a string to `__tablename__` gets the `tablename` property.
"""

import ast
from collections.abc import Mapping, Sequence
from typing import ClassVar

from memex.graph.model import ClassNode, Edge
from memex.ingest.code.parser import ParsedModule
from memex.ingest.code.resolver import SymbolTable

_KINDS = {"ForeignKey": "foreign_key", "relationship": "relationship"}


class SqlAlchemyExtractor:
    name: ClassVar[str] = "sqlalchemy"

    def extract(self, modules: Sequence[ParsedModule], symbols: SymbolTable) -> list[Edge]:
        edges: dict[tuple[str, str, str, str], Edge] = {}
        for module, cls, definition in _classes(modules):
            for statement in definition.body:
                assigned = _assignment(statement)
                if assigned is None:
                    continue
                attr, value = assigned
                for call in _calls_in(value):
                    kind = _kind(module, call, symbols)
                    if kind is None or not call.args:
                        continue
                    if kind == "foreign_key":
                        target = _foreign_key_target(module, call.args[0], symbols)
                    else:
                        target = _relationship_target(module, call.args[0], symbols)
                    if target is None:
                        continue
                    target_id = symbols.nodes[target].id
                    edges.setdefault(
                        (cls.id, target_id, kind, attr),
                        Edge(
                            kind="REFERENCES",
                            source=cls.id,
                            target=target_id,
                            ref_kind=kind,
                            attr=attr,
                            line=call.lineno,
                            extractor=self.name,
                        ),
                    )
        return list(edges.values())

    def class_properties(
        self, modules: Sequence[ParsedModule], symbols: SymbolTable
    ) -> Mapping[str, Mapping[str, str]]:
        properties: dict[str, dict[str, str]] = {}
        for _, cls, _ in _classes(modules):
            tablename = symbols.class_attributes(cls.qualname).get("__tablename__")
            if tablename is not None:
                properties[cls.id] = {"tablename": tablename}
        return properties


def _classes(
    modules: Sequence[ParsedModule],
) -> list[tuple[ParsedModule, ClassNode, ast.ClassDef]]:
    found = []
    for module in modules:
        for node in module.nodes:
            definition = module.definitions.get(node.qualname)
            if isinstance(node, ClassNode) and isinstance(definition, ast.ClassDef):
                found.append((module, node, definition))
    return found


def _assignment(statement: ast.stmt) -> tuple[str, ast.expr] | None:
    """(attribute, value) for `name = value` or `name: T = value`, else None."""
    match statement:
        case ast.Assign(targets=[ast.Name(id=name)], value=value):
            return name, value
        case ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value):
            return name, value
    return None


def _calls_in(expr: ast.expr) -> list[ast.Call]:
    """Every call inside an expression, in source order. Iterative."""
    found: list[ast.Call] = []
    stack: list[ast.AST] = [expr]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Call):
            found.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return sorted(found, key=lambda call: (call.lineno, call.col_offset))


def _kind(module: ParsedModule, call: ast.Call, symbols: SymbolTable) -> str | None:
    """`foreign_key` or `relationship` if the call is that SQLAlchemy function, else None."""
    resolved = symbols.resolve_expression(module, call.func)
    if resolved is None or not resolved[1]:
        return None
    dotted = resolved[0]
    if not dotted.startswith("sqlalchemy."):
        return None
    return _KINDS.get(dotted.rsplit(".", 1)[-1])


def _foreign_key_target(
    module: ParsedModule, argument: ast.expr, symbols: SymbolTable
) -> str | None:
    if isinstance(argument, ast.Attribute):  # ForeignKey(User.id)
        return _class(symbols.resolve_expression(module, argument.value), symbols)
    if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
        return None
    parts = argument.value.split(".")
    if len(parts) < 2:
        return None
    for table in dict.fromkeys((".".join(parts[:-1]), parts[-2])):  # with schema, then without
        classes = symbols.by_class_attribute("__tablename__", table)
        if classes:
            return classes[0] if len(classes) == 1 else None
    return None


def _relationship_target(
    module: ParsedModule, argument: ast.expr, symbols: SymbolTable
) -> str | None:
    if isinstance(argument, ast.Lambda):
        argument = argument.body
    if not isinstance(argument, ast.Constant):
        return _class(symbols.resolve_expression(module, argument), symbols)
    if not isinstance(argument.value, str):
        return None
    name = argument.value
    if name.isidentifier():
        bound = _class(symbols.resolve_name(module, name), symbols)
        if bound is not None and _is_mapped(bound, symbols):
            return bound
    if name in symbols.classes and _is_mapped(name, symbols):
        return name
    candidates = [cls for cls in symbols.classes_by_name.get(name, []) if _is_mapped(cls, symbols)]
    return candidates[0] if len(candidates) == 1 else None


def _is_mapped(cls: str, symbols: SymbolTable) -> bool:
    """True if the class or an in-codebase ancestor has a `__tablename__` or a base under
    `sqlalchemy` (such as `DeclarativeBase`)."""
    return any(
        "__tablename__" in symbols.class_attributes(ancestor)
        or any(
            resolved is not None and resolved[1] and resolved[0].startswith("sqlalchemy.")
            for resolved in symbols.written_bases(ancestor)
        )
        for ancestor in symbols.ancestors(cls)
    )


def _class(resolved: tuple[str, bool] | None, symbols: SymbolTable) -> str | None:
    """The in-codebase class a resolved name is, or None."""
    if resolved is None or resolved[1] or resolved[0] not in symbols.classes:
        return None
    return resolved[0]
