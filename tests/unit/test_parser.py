from pathlib import Path
from textwrap import dedent

from memex.config import load_config
from memex.graph.model import ClassNode, Edge, FunctionNode, ModuleNode, ParseError, code_id
from memex.ingest.code.parser import ParsedModule, RawImport, parse_module
from memex.ingest.code.walker import SourceFile, walk

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAYERED_APP = load_config(FIXTURES / "memex.toml").get("layered_app")
CB = "layered_app"


def parse_fixture(path: str) -> ParsedModule:
    source = next(file for file in walk(LAYERED_APP) if file.path == path)
    parsed = parse_module(CB, source, (LAYERED_APP.root / path).read_bytes())
    assert isinstance(parsed, ParsedModule)
    return parsed


def parse_text(text: str) -> ParsedModule | ParseError:
    source = SourceFile(path="pkg/m.py", qualname="pkg.m", package="pkg")
    return parse_module("lib", source, dedent(text).encode())


def defines(parsed: ParsedModule) -> set[tuple[str, str]]:
    return {(edge.source, edge.target) for edge in parsed.defines}


def test_class_with_method_gives_exact_nodes_and_defines_edges() -> None:
    parsed = parse_fixture("app/services/user_services/user_service.py")
    module = "app.services.user_services.user_service"

    assert parsed.nodes == (
        ModuleNode(
            id=code_id(CB, module),
            codebase=CB,
            qualname=module,
            path="app/services/user_services/user_service.py",
            docstring="Business logic for users.",
        ),
        ClassNode(
            id=code_id(CB, f"{module}.UserService"),
            codebase=CB,
            name="UserService",
            qualname=f"{module}.UserService",
            path="app/services/user_services/user_service.py",
            line=7,
            end_line=12,
            docstring="Reads users through the injected repositories.",
        ),
        FunctionNode(
            id=code_id(CB, f"{module}.UserService.get"),
            codebase=CB,
            name="get",
            qualname=f"{module}.UserService.get",
            path="app/services/user_services/user_service.py",
            line=10,
            end_line=12,
            signature="get(self, user_id: int) -> UserOut",
            is_method=True,
            is_async=False,
        ),
    )
    assert parsed.defines == (
        Edge(
            kind="DEFINES",
            source=code_id(CB, module),
            target=code_id(CB, f"{module}.UserService"),
        ),
        Edge(
            kind="DEFINES",
            source=code_id(CB, f"{module}.UserService"),
            target=code_id(CB, f"{module}.UserService.get"),
        ),
    )
    assert parsed.imports == (
        RawImport(module="app._base", name="BaseService", alias=None, level=0, line=3),
        RawImport(module="app.schema.user", name="UserOut", alias=None, level=0, line=4),
    )


def test_functions_inside_functions_get_no_node_but_their_imports_count() -> None:
    parsed = parse_fixture("app/main.py")

    assert [node.qualname for node in parsed.nodes] == [
        "app.main",
        "app.main.create_app",
        "app.main.run",
    ]
    assert parsed.imports == (
        RawImport(module="fastapi", name="FastAPI", alias=None, level=0, line=3),
        RawImport(module="app.routes", name="orders", alias=None, level=0, line=5),
        RawImport(module="app.routes", name="users", alias=None, level=0, line=5),
        RawImport(module="uvicorn", name=None, alias=None, level=0, line=22),
    )


def test_decorated_async_function_and_relative_imports() -> None:
    parsed = parse_fixture("app/routes/orders/api.py")

    function = parsed.nodes[-1]
    assert isinstance(function, FunctionNode)
    assert (function.name, function.line, function.end_line) == ("get_order", 13, 14)
    assert function.is_async and not function.is_method
    assert function.signature == "get_order(order_id: int) -> order.OrderOut"
    assert function.docstring is None
    assert parsed.imports[1:] == (
        RawImport(
            module="repos.repository_factory", name="AllRepositories", alias=None, level=3, line=5
        ),
        RawImport(module="schema", name="order", alias=None, level=3, line=6),
        RawImport(
            module="services.order_services.order_service",
            name="OrderService",
            alias=None,
            level=3,
            line=7,
        ),
    )


def test_star_imports_and_imports_under_if_blocks() -> None:
    schema = parse_fixture("app/schema/__init__.py")
    users = parse_fixture("app/db/models/users.py")

    assert schema.nodes[0].qualname == "app.schema"
    assert schema.nodes[0].docstring is None
    assert schema.imports == (
        RawImport(module="order", name="*", alias=None, level=1, line=1),
        RawImport(module="user", name="*", alias=None, level=1, line=2),
    )
    assert RawImport(module="orders", name="Order", alias=None, level=1, line=11) in users.imports


def test_plain_imports_keep_dotted_names_and_aliases() -> None:
    parsed = parse_text("import a.b as c, d\nfrom . import e as f\n")

    assert isinstance(parsed, ParsedModule)
    assert parsed.imports == (
        RawImport(module="a.b", name=None, alias="c", level=0, line=1),
        RawImport(module="d", name=None, alias=None, level=0, line=1),
        RawImport(module=None, name="e", alias="f", level=1, line=2),
    )


def test_nested_classes_get_nodes_defined_by_their_class() -> None:
    parsed = parse_text(
        """\
        class Outer:
            class Meta:
                table = "outer"

            def method(self): ...
        """
    )

    assert isinstance(parsed, ParsedModule)
    assert defines(parsed) == {
        ("lib:pkg.m", "lib:pkg.m.Outer"),
        ("lib:pkg.m.Outer", "lib:pkg.m.Outer.Meta"),
        ("lib:pkg.m.Outer", "lib:pkg.m.Outer.method"),
    }
    method = parsed.nodes[-1]
    assert isinstance(method, FunctionNode) and method.is_method


def test_conditional_definitions_get_one_node_each() -> None:
    parsed = parse_text(
        '''\
        """First line.

        More detail."""
        try:
            from fast import dumps
        except ImportError:
            def dumps(obj): ...
        if True:
            def dumps(obj): ...
        '''
    )

    assert isinstance(parsed, ParsedModule)
    assert parsed.nodes[0].docstring == "First line."
    assert [node.qualname for node in parsed.nodes] == ["pkg.m", "pkg.m.dumps"]
    assert parsed.nodes[1].line == 7  # the first definition wins
    assert defines(parsed) == {("lib:pkg.m", "lib:pkg.m.dumps")}


def test_syntax_error_is_reported_not_raised() -> None:
    parsed = parse_text("x = 1\ndef broken(:\n")

    assert isinstance(parsed, ParseError)
    assert (parsed.path, parsed.line) == ("pkg/m.py", 2)
    assert parsed.message
