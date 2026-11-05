import warnings
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
        RawImport(module="uvicorn", name=None, alias=None, level=0, line=22, module_level=False),
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


def test_imports_inside_functions_and_classes_are_not_module_level() -> None:
    parsed = parse_text(
        """\
        import a
        if a:
            import b
        class C:
            import c
        def f():
            import d
        """
    )

    assert isinstance(parsed, ParsedModule)
    assert [(raw.module, raw.module_level) for raw in parsed.imports] == [
        ("a", True),
        ("b", True),
        ("c", False),
        ("d", False),
    ]


def test_definitions_in_every_kind_of_block_get_nodes() -> None:
    parsed = parse_text(
        """\
        with ctx:
            def in_with(): ...
        match mode:
            case "a":
                def in_match(): ...
        for _ in items:
            pass
        else:
            def in_for_else(): ...
        while flag:
            def in_while(): ...
        try:
            pass
        except* ValueError:
            def in_except_star(): ...
        finally:
            def in_finally(): ...
        class C:
            if flag:
                def in_class_if(self): ...
        """
    )

    assert isinstance(parsed, ParsedModule)
    assert [node.qualname.removeprefix("pkg.m.") for node in parsed.nodes[1:]] == [
        "in_with",
        "in_match",
        "in_for_else",
        "in_while",
        "in_except_star",
        "in_finally",
        "C",
        "C.in_class_if",
    ]


def test_overload_stubs_give_way_to_the_implementation() -> None:
    parsed = parse_text(
        '''\
        from typing import overload
        import typing

        class C:
            @overload
            def get(self, x: int) -> int: ...
            @typing.overload
            def get(self, x: str) -> str: ...
            def get(self, x):
                """The implementation."""
                return x
        '''
    )

    assert isinstance(parsed, ParsedModule)
    [get] = [node for node in parsed.nodes if node.qualname == "pkg.m.C.get"]
    assert isinstance(get, FunctionNode)
    assert (get.line, get.end_line, get.signature) == (9, 11, "get(self, x)")
    assert get.docstring == "The implementation."
    assert len([edge for edge in parsed.defines if edge.target == "lib:pkg.m.C.get"]) == 1


def test_coding_cookie_and_byte_order_mark_are_honored() -> None:
    source = SourceFile(path="pkg/m.py", qualname="pkg.m", package="pkg")
    latin1 = "# -*- coding: latin-1 -*-\n'''Caf\xe9 menu.'''\n".encode("latin-1")
    bom = b"\xef\xbb\xbf'''With a BOM.'''\n"

    parsed_latin1 = parse_module("lib", source, latin1)
    parsed_bom = parse_module("lib", source, bom)

    assert isinstance(parsed_latin1, ParsedModule)
    assert parsed_latin1.nodes[0].docstring == "Caf\xe9 menu."
    assert isinstance(parsed_bom, ParsedModule)
    assert parsed_bom.nodes[0].docstring == "With a BOM."


def test_undecodable_bytes_are_a_parse_error() -> None:
    source = SourceFile(path="pkg/m.py", qualname="pkg.m", package="pkg")

    parsed = parse_module("lib", source, b"x = '\xff'\n")

    assert isinstance(parsed, ParseError)
    assert parsed.path == "pkg/m.py"


def test_expression_too_deep_to_compile_is_a_parse_error() -> None:
    parsed = parse_text("x = " + "1+" * 200_000 + "1\n")

    assert isinstance(parsed, ParseError)
    assert parsed.line is None


def test_syntax_warnings_neither_print_nor_fail() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # as under `python -W error`
        parsed = parse_text("pattern = '\\d+'\n")

    assert isinstance(parsed, ParsedModule)


def test_deep_expression_that_parses_still_gives_nodes_and_imports() -> None:
    # 5,000 terms parse fine but overflow a recursive walk and ast.unparse.
    parsed = parse_text("import a\ndef f(x=" + "1+" * 5_000 + "1): ...\nimport b\n")

    assert isinstance(parsed, ParsedModule)
    function = parsed.nodes[1]
    assert isinstance(function, FunctionNode)
    assert function.signature == "f(...)"
    assert [raw.module for raw in parsed.imports] == ["a", "b"]
