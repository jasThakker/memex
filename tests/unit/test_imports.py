from pathlib import Path
from textwrap import dedent

import pytest

from memex.config import load_config
from memex.graph.model import Edge, ExternalNode, code_id
from memex.ingest.code.parser import ParsedModule, parse_module
from memex.ingest.code.resolver import link_imports
from memex.ingest.code.walker import SourceFile, walk

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGISTRY = load_config(FIXTURES / "memex.toml")


def parse_codebase(name: str) -> list[ParsedModule]:
    codebase = REGISTRY.get(name)
    modules = []
    for source in walk(codebase):
        parsed = parse_module(name, source, (codebase.root / source.path).read_bytes())
        assert isinstance(parsed, ParsedModule)
        modules.append(parsed)
    return modules


def parse_files(files: dict[str, str]) -> list[ParsedModule]:
    """Parse inline modules of a codebase called `lib`, keyed by path."""
    modules = []
    for path, text in files.items():
        parts = path.removesuffix(".py").split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        source = SourceFile(path=path, qualname=".".join(parts), package=parts[0])
        parsed = parse_module("lib", source, dedent(text).encode())
        assert isinstance(parsed, ParsedModule)
        modules.append(parsed)
    return modules


def imports_from(edges: list[Edge], codebase: str, module: str) -> set[tuple[str, tuple[str, ...]]]:
    """(target without the codebase prefix, names) for each IMPORTS edge leaving `module`."""
    source = code_id(codebase, module)
    return {
        (edge.target.removeprefix(f"{codebase}:"), edge.names)
        for edge in edges
        if edge.source == source
    }


LAYERED_EDGES, LAYERED_EXTERNALS = link_imports("layered_app", parse_codebase("layered_app"))


def test_every_edge_is_an_import_with_a_line() -> None:
    assert LAYERED_EDGES
    assert all(edge.kind == "IMPORTS" and edge.line for edge in LAYERED_EDGES)


def test_names_resolve_to_submodules_classes_or_externals() -> None:
    assert imports_from(LAYERED_EDGES, "layered_app", "app.main") == {
        ("ext:fastapi.FastAPI", ("FastAPI",)),
        ("app.routes.orders", ("orders",)),
        ("app.routes.users", ("users",)),
        ("ext:uvicorn", ()),
    }
    # Relative imports resolve against the importing module's package.
    assert imports_from(LAYERED_EDGES, "layered_app", "app.routes.orders.api") == {
        ("ext:fastapi.APIRouter", ("APIRouter",)),
        ("app.repos.repository_factory.AllRepositories", ("AllRepositories",)),
        ("app.schema.order", ("order",)),
        ("app.services.order_services.order_service.OrderService", ("OrderService",)),
    }


def test_import_inside_a_function_keeps_its_line() -> None:
    uvicorn = next(edge for edge in LAYERED_EDGES if edge.target == "layered_app:ext:uvicorn")

    assert uvicorn.line == 22


def test_reexports_reach_the_defining_class() -> None:
    assert imports_from(
        LAYERED_EDGES, "layered_app", "app.services.user_services.user_service"
    ) == {
        ("app._base.service.BaseService", ("BaseService",)),  # via app/_base/__init__.py
        ("app.schema.user.UserOut", ("UserOut",)),
    }
    assert (
        "app.services.user_services.user_service.UserService",
        ("UserService",),
    ) in imports_from(LAYERED_EDGES, "layered_app", "app.routes.users.api")
    assert imports_from(LAYERED_EDGES, "layered_app", "app.repos.repository_users") == {
        ("app.db.models.users.User", ("User",)),
    }

    plain_edges, _ = link_imports("plainrepo", parse_codebase("plainrepo"))
    assert ("toolkit._client.Client", ("Client",)) in imports_from(
        plain_edges, "plainrepo", "reporter.cli"
    )


def test_names_that_are_not_symbols_fall_back_to_their_module() -> None:
    assert imports_from(LAYERED_EDGES, "layered_app", "app") == {
        ("app.__version__", ("__version__",)),  # a variable
    }
    assert imports_from(LAYERED_EDGES, "layered_app", "app.routes.users") == {
        ("app.routes.users.api", ("router",)),
    }


def test_star_import_gives_one_edge_to_the_module() -> None:
    assert imports_from(LAYERED_EDGES, "layered_app", "app.schema") == {
        ("app.schema.order", ("*",)),
        ("app.schema.user", ("*",)),
    }


def test_imports_under_type_checking_count() -> None:
    assert ("app.db.models.orders.Order", ("Order",)) in imports_from(
        LAYERED_EDGES, "layered_app", "app.db.models.users"
    )


def test_outside_names_become_external_nodes_scoped_by_codebase() -> None:
    by_name = {external.name: external for external in LAYERED_EXTERNALS}

    assert by_name["pydantic.BaseModel"] == ExternalNode(
        id="layered_app:ext:pydantic.BaseModel", codebase="layered_app", name="pydantic.BaseModel"
    )
    assert {"uvicorn", "sqlalchemy.orm.DeclarativeBase", "typing.TYPE_CHECKING"} <= set(by_name)
    assert not [name for name in by_name if name.split(".")[0] == "app"]
    assert len(by_name) == len(LAYERED_EXTERNALS)  # no duplicates


def test_reexport_through_a_star_import() -> None:
    edges, _ = link_imports(
        "lib",
        parse_files(
            {
                "pkg/__init__.py": "from .impl import *\n",
                "pkg/impl.py": "def helper(): ...\n",
                "pkg/use.py": "from pkg import helper\n",
            }
        ),
    )

    assert imports_from(edges, "lib", "pkg.use") == {("pkg.impl.helper", ("helper",))}


def test_reexport_chains_stop_after_five_hops_and_cycles_terminate() -> None:
    files = {f"pkg/m{i}.py": f"from pkg.m{i + 1} import x\n" for i in range(6)}
    files["pkg/m6.py"] = "def x(): ...\n"
    files["pkg/a.py"] = "from pkg.b import y\n"
    files["pkg/b.py"] = "from pkg.a import y\n"
    files["pkg/use.py"] = "from pkg.m1 import x\nfrom pkg.m0 import x as x0\nfrom pkg.a import y\n"

    edges, _ = link_imports("lib", parse_files(files))

    assert imports_from(edges, "lib", "pkg.use") == {
        ("pkg.m6.x", ("x",)),  # five hops: m1 -> m2 -> m3 -> m4 -> m5 -> m6
        ("pkg.m0", ("x",)),  # six hops: gives up and points at the module
        ("pkg.a", ("y",)),  # a cycle, so no definition is ever found
    }


def test_names_falling_back_to_the_same_module_share_one_edge() -> None:
    edges, _ = link_imports(
        "lib",
        parse_files(
            {
                "pkg/consts.py": "A = 1\nB = 2\n",
                "pkg/use.py": "from pkg.consts import A, B\nfrom pkg.consts import A\n",
            }
        ),
    )

    [edge] = [edge for edge in edges if edge.source == "lib:pkg.use"]
    assert (edge.target, edge.names, edge.line) == ("lib:pkg.consts", ("A", "B"), 1)


def test_relative_import_above_the_top_package_is_dropped() -> None:
    edges, externals = link_imports("lib", parse_files({"pkg/m.py": "from ... import x\n"}))

    assert edges == []
    assert externals == []


def resolve_use(files: dict[str, str]) -> set[tuple[str, tuple[str, ...]]]:
    """Import edges leaving `pkg.use` in a codebase made of `files`."""
    edges, _ = link_imports("lib", parse_files(files))
    return imports_from(edges, "lib", "pkg.use")


def test_reexport_of_a_name_shadows_the_submodule_it_comes_from() -> None:
    assert resolve_use(
        {
            "pkg/__init__.py": "from .api import api\n",
            "pkg/api.py": "def api(): ...\n",
            "pkg/use.py": "from pkg import api\n",
        }
    ) == {("pkg.api.api", ("api",))}


def test_from_import_of_a_submodule_still_reaches_the_module() -> None:
    assert resolve_use(
        {
            "pkg/__init__.py": "from . import api\n",
            "pkg/api.py": "def api(): ...\n",
            "pkg/use.py": "from pkg import api\n",
        }
    ) == {("pkg.api", ("api",))}


@pytest.mark.parametrize("first, second", [("_speedups", "_pure"), ("_pure", "_speedups")])
def test_a_binding_that_cannot_be_resolved_falls_back_to_another(first: str, second: str) -> None:
    assert resolve_use(
        {
            "pkg/__init__.py": f"try:\n    from .{first} import encode\n"
            f"except ImportError:\n    from .{second} import encode\n",
            "pkg/_pure.py": "def encode(): ...\n",  # _speedups is a compiled module, never walked
            "pkg/use.py": "from pkg import encode\n",
        }
    ) == {("pkg._pure.encode", ("encode",))}


def test_the_last_module_level_binding_wins_and_local_imports_are_not_exports() -> None:
    assert resolve_use(
        {
            "pkg/__init__.py": "from .old import Thing\nfrom .fast import Thing\n"
            "def _lazy():\n    from .slow import Thing\n",
            "pkg/old.py": "class Thing: ...\n",
            "pkg/fast.py": "class Thing: ...\n",
            "pkg/slow.py": "class Thing: ...\n",
            "pkg/use.py": "from pkg import Thing\n",
        }
    ) == {("pkg.fast.Thing", ("Thing",))}


def test_star_reexports_skip_underscore_names() -> None:
    assert resolve_use(
        {
            "pkg/__init__.py": "from .impl import *\n",
            "pkg/impl.py": "def public(): ...\ndef _private(): ...\n",
            "pkg/use.py": "from pkg import public, _private\n",
        }
    ) == {("pkg.impl.public", ("public",)), ("pkg", ("_private",))}


def test_explicit_binding_wins_over_a_star_import() -> None:
    assert resolve_use(
        {
            "pkg/__init__.py": "from .a import *\nfrom .b import thing\n",
            "pkg/a.py": "def thing(): ...\n",
            "pkg/b.py": "def thing(): ...\n",
            "pkg/use.py": "from pkg import thing\n",
        }
    ) == {("pkg.b.thing", ("thing",))}


def test_aliased_reexports_are_followed() -> None:
    assert resolve_use(
        {
            "pkg/__init__.py": "from .impl import helper as public\n"
            "import pkg.tools.text as text_utils\n",
            "pkg/impl.py": "def helper(): ...\n",
            "pkg/tools/text.py": "def wrap(): ...\n",
            "pkg/use.py": "from pkg import public, text_utils\n",
        }
    ) == {("pkg.impl.helper", ("public",)), ("pkg.tools.text", ("text_utils",))}


def test_plain_import_of_an_internal_module() -> None:
    assert resolve_use(
        {
            "pkg/__init__.py": "",
            "pkg/tools/text.py": "def wrap(): ...\n",
            "pkg/use.py": "import pkg.tools.text\n",
        }
    ) == {("pkg.tools.text", ())}


def test_names_under_the_codebase_packages_never_become_externals() -> None:
    edges, externals = link_imports(
        "lib",
        parse_files(
            {
                "pkg/__init__.py": "",
                # pkg/migrations/ is excluded, pkg/_native is compiled: neither was walked.
                "pkg/use.py": "import pkg.migrations.env\nfrom pkg.migrations import env\n"
                "from pkg._native import fast\nfrom ._native import *\n",
            }
        ),
    )

    assert imports_from(edges, "lib", "pkg.use") == set()
    assert externals == []
