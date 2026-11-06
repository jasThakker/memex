"""Parse one module with `ast` into nodes, DEFINES edges and raw imports.

Classes and functions get nodes when defined at module level or in a class body, including
inside `if`, `try`, `with`, `match` and loop blocks there. If a name is defined twice, the
first definition wins, except that `@overload` stubs give way to the next definition.
Anything defined inside a function gets no node (DESIGN.md section 13). Imports are collected
from the whole module, functions included. Turning them into IMPORTS edges is the resolver's
job.
"""

import ast
import warnings
from dataclasses import dataclass, field

from memex.graph.model import ClassNode, Edge, FunctionNode, ModuleNode, ParseError, code_id
from memex.ingest.code.walker import SourceFile

CodeNode = ModuleNode | ClassNode | FunctionNode
Definition = ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class RawImport:
    """One imported name, as written.

    `import a.b as c` gives module "a.b", no name, alias "c". `from ..m import x` gives
    module "m", name "x", level 2. `from . import x` has no module. A star import has name "*".
    `module_level` is False for imports inside a function or class body: those bind local
    names, so they are not the module's exports.
    """

    module: str | None
    name: str | None
    alias: str | None
    level: int
    line: int
    module_level: bool = True


@dataclass(frozen=True, eq=False)
class ParsedModule:
    source: SourceFile
    tree: ast.Module
    nodes: tuple[CodeNode, ...]  # the module first, then definitions in source order
    defines: tuple[Edge, ...]
    imports: tuple[RawImport, ...]  # in source order
    definitions: dict[str, Definition] = field(default_factory=dict)  # qualname -> its AST


# Parse stage of indexing: parses one file with `ast` into Module/Class/Function nodes, DEFINES
# edges and raw imports. A syntax error returns a ParseError, never raises. Called once per file by
# index_code.
def parse_module(codebase: str, source: SourceFile, data: bytes) -> ParsedModule | ParseError:
    """Parse one file's bytes. A file `ast` cannot parse gives a ParseError, never an exception.

    Bytes, not text, so `ast` honors a coding declaration or byte order mark.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)  # e.g. invalid escape sequences
            tree = ast.parse(data, filename=source.path)
    except SyntaxError as error:  # also undecodable bytes and unknown encodings
        return ParseError(path=source.path, line=error.lineno, message=error.msg)
    except RecursionError:
        return ParseError(path=source.path, line=None, message="too deeply nested to parse")

    module = ModuleNode(
        id=code_id(codebase, source.qualname),
        codebase=codebase,
        qualname=source.qualname,
        path=source.path,
        docstring=_first_docstring_line(tree),
    )
    collector = _Collector(codebase, source.path, module)
    collector.visit_body(tree.body, module)
    return ParsedModule(
        source=source,
        tree=tree,
        nodes=tuple(collector.nodes.values()),
        defines=tuple(collector.defines),
        imports=_imports(tree),
        definitions=collector.definitions,
    )


class _Collector:
    """Walks module and class bodies, creating nodes and DEFINES edges."""

    # Sets up the per-file state: nodes so far (starting with the module), DEFINES edges, overload
    # stubs and each definition's ast node.
    def __init__(self, codebase: str, path: str, module: ModuleNode) -> None:
        self.codebase = codebase
        self.path = path
        self.nodes: dict[str, CodeNode] = {module.qualname: module}
        self.defines: list[Edge] = []
        self.overload_stubs: set[str] = set()
        self.definitions: dict[str, Definition] = {}

    # Walks a module or class body: classes and functions get nodes; other statements (if, try,
    # with...) are searched for definitions nested inside them.
    def visit_body(self, body: list[ast.stmt], parent: ModuleNode | ClassNode) -> None:
        for statement in body:
            match statement:
                case ast.ClassDef():
                    self._add_class(statement, parent)
                case ast.FunctionDef() | ast.AsyncFunctionDef():
                    self._add_function(statement, parent)
                case _:
                    for block in _blocks(statement):
                        self.visit_body(block, parent)

    # Helper for visit_body: creates a ClassNode, then visits the class body so its methods become
    # nodes too.
    def _add_class(self, node: ast.ClassDef, parent: ModuleNode | ClassNode) -> None:
        qualname = f"{parent.qualname}.{node.name}"
        if qualname in self.nodes:
            return
        cls = ClassNode(
            id=code_id(self.codebase, qualname),
            codebase=self.codebase,
            name=node.name,
            qualname=qualname,
            path=self.path,
            line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            docstring=_first_docstring_line(node),
        )
        self._add(cls, parent)
        self.definitions[qualname] = node
        self.visit_body(node.body, cls)

    # Helper for visit_body: creates a FunctionNode with its signature and docstring line; an
    # @overload stub is replaced by the real definition.
    def _add_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, parent: ModuleNode | ClassNode
    ) -> None:
        qualname = f"{parent.qualname}.{node.name}"
        if qualname in self.nodes and qualname not in self.overload_stubs:
            return
        function = FunctionNode(
            id=code_id(self.codebase, qualname),
            codebase=self.codebase,
            name=node.name,
            qualname=qualname,
            path=self.path,
            line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            signature=_signature(node),
            is_method=isinstance(parent, ClassNode),
            is_async=isinstance(node, ast.AsyncFunctionDef),
            docstring=_first_docstring_line(node),
        )
        if qualname in self.nodes:  # replacing an overload stub keeps its DEFINES edge
            self.nodes[qualname] = function
        else:
            self._add(function, parent)
        self.definitions[qualname] = node
        if _is_overload(node):
            self.overload_stubs.add(qualname)
        else:
            self.overload_stubs.discard(qualname)

    # Helper: stores a node and adds the DEFINES edge from its parent.
    def _add(self, node: ClassNode | FunctionNode, parent: ModuleNode | ClassNode) -> None:
        self.nodes[node.qualname] = node
        self.defines.append(Edge(kind="DEFINES", source=parent.id, target=node.id))


# Helper for visit_body: the statement lists nested inside a compound statement (if/else,
# try/except, with, for...), so definitions there are found.
def _blocks(statement: ast.stmt) -> list[list[ast.stmt]]:
    """Statement lists nested in a compound statement, in source order."""
    blocks: list[list[ast.stmt]] = [getattr(statement, "body", [])]
    blocks += [handler.body for handler in getattr(statement, "handlers", [])]
    blocks += [getattr(statement, field, []) for field in ("orelse", "finalbody")]
    blocks += [case.body for case in getattr(statement, "cases", [])]
    return blocks


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


# Helper for parse_module: every import statement as a RawImport (text as written, resolved later in
# step 4). Iterative, so deep code does not recurse.
def _imports(tree: ast.Module) -> tuple[RawImport, ...]:
    """Every import statement, in source order. Iterative: deep expressions must not recurse."""
    statements: list[tuple[ast.Import | ast.ImportFrom, bool]] = []
    stack: list[tuple[ast.AST, bool]] = [(tree, True)]
    while stack:
        node, module_level = stack.pop()
        if isinstance(node, ast.Import | ast.ImportFrom):
            statements.append((node, module_level))
            continue
        inner = module_level and not isinstance(node, _SCOPES)
        stack.extend((child, inner) for child in ast.iter_child_nodes(node))
    statements.sort(key=lambda item: (item[0].lineno, item[0].col_offset))

    found: list[RawImport] = []
    for statement, module_level in statements:
        if isinstance(statement, ast.Import):
            found += [
                RawImport(
                    module=alias.name,
                    name=None,
                    alias=alias.asname,
                    level=0,
                    line=statement.lineno,
                    module_level=module_level,
                )
                for alias in statement.names
            ]
        else:
            found += [
                RawImport(
                    module=statement.module,
                    name=alias.name,
                    alias=alias.asname,
                    level=statement.level,
                    line=statement.lineno,
                    module_level=module_level,
                )
                for alias in statement.names
            ]
    return tuple(found)


# Helper for _add_function: True for a function decorated with @overload or @typing.overload.
def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True for `@overload` and `@typing.overload` (or any `@<module>.overload`)."""
    return any(
        (isinstance(decorator, ast.Name) and decorator.id == "overload")
        or (isinstance(decorator, ast.Attribute) and decorator.attr == "overload")
        for decorator in node.decorator_list
    )


# Helper for _add_function: 'name(args) -> return' as text, via ast.unparse; falls back to
# 'name(...)' if a default is too deeply nested.
def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        signature = f"{node.name}({ast.unparse(node.args)})"
        if node.returns is not None:
            signature += f" -> {ast.unparse(node.returns)}"
    except RecursionError:  # a default value too deeply nested to print
        return f"{node.name}(...)"
    return signature


# Helper: the first non-blank docstring line of a module, class or function, or None. Stored on the
# node for find_symbol results.
def _first_docstring_line(
    node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    docstring = ast.get_docstring(node)
    if not docstring:
        return None
    return next((line.strip() for line in docstring.splitlines() if line.strip()), None)
