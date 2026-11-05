"""CALLS edges: Function -> Function with a confidence label, and the unresolved count.

Resolution order is DESIGN.md section 9. A call whose head is a builtin, a literal or a name
imported from outside the codebase is external: no edge, and not unresolved. A constructor
call of a class with no `__init__` in the codebase (or its bases) gives no edge and is not
unresolved either.
"""

from parsing import REGISTRY, parse_codebase, parse_files

from memex.graph.model import Edge
from memex.ingest.code import index_code
from memex.ingest.code.resolver import SymbolTable, link_calls


def calls(edges: list[Edge], codebase: str) -> set[tuple[str, str, str | None]]:
    """(caller, callee, confidence) for each CALLS edge, without the codebase prefix."""
    prefix = f"{codebase}:"
    return {
        (edge.source.removeprefix(prefix), edge.target.removeprefix(prefix), edge.confidence)
        for edge in edges
    }


def link(files: dict[str, str]) -> tuple[list[Edge], int]:
    return link_calls("lib", SymbolTable(parse_files(files)))


ORDER_SERVICE = "app.services.order_services.order_service.OrderService"
USER_SERVICE = "app.services.user_services.user_service.UserService"
BASE_INIT = "app._base.service.BaseService.__init__"
REPOS_INIT = "app.repos.repository_factory.AllRepositories.__init__"
USER_REPO = "app.repos.repository_users.UserRepository"


def test_layered_app_calls_and_confidences() -> None:
    edges, unresolved = link_calls("layered_app", SymbolTable(parse_codebase("layered_app")))

    assert all(edge.kind == "CALLS" and edge.line for edge in edges)
    assert calls(edges, "layered_app") == {
        ("app.main.run", "app.main.create_app", "exact"),  # local function
        # constructors resolve to __init__, then `C(...).m()` to C's method
        ("app.routes.orders.api.get_order", f"{ORDER_SERVICE}.__init__", "exact"),
        ("app.routes.orders.api.get_order", REPOS_INIT, "exact"),
        ("app.routes.orders.api.get_order", f"{ORDER_SERVICE}.get", "exact"),
        ("app.routes.users.api.get_user", BASE_INIT, "exact"),  # inherited __init__
        ("app.routes.users.api.get_user", REPOS_INIT, "exact"),
        ("app.routes.users.api.get_user", f"{USER_SERVICE}.get", "exact"),
        (f"{ORDER_SERVICE}.__init__", BASE_INIT, "exact"),  # super().__init__
        (f"{ORDER_SERVICE}.create", f"{ORDER_SERVICE}.__init__", "exact"),  # cls(...)
        (f"{ORDER_SERVICE}.create", f"{ORDER_SERVICE}.default_repos", "exact"),  # cls.m()
        (f"{ORDER_SERVICE}.default_repos", REPOS_INIT, "exact"),
        (f"{ORDER_SERVICE}.owner_name", f"{ORDER_SERVICE}.get", "exact"),  # self.m()
        # injected attribute, unique method name
        (f"{ORDER_SERVICE}.owner_name", f"{USER_REPO}.get_name", "inferred"),
        (f"{USER_REPO}.get_name", f"{USER_REPO}.get_one", "exact"),
    }
    # create_app: register(...) twice (a nested def, no node) and application.include_router;
    # OrderService.get and UserService.get: self.repos.<x>.get_one (two methods named get_one).
    assert unresolved == 5


def test_plainrepo_calls_and_confidences() -> None:
    edges, unresolved = link_calls("plainrepo", SymbolTable(parse_codebase("plainrepo")))

    assert calls(edges, "plainrepo") == {
        ("reporter.cli.main", "toolkit._client.Client.__init__", "exact"),  # via re-export
        ("reporter.cli.main", "toolkit._client.Client.send", "exact"),  # Client().send()
        ("reporter.cli.main", "reporter.formats.table.render_table", "exact"),  # module alias
        ("toolkit._client.Client.send", "toolkit.text.slug.slugify", "exact"),
    }
    # parser.add_argument, parser.parse_args, self.transport.send (three methods named send),
    # payload.encode, title.lower. Not counted: argparse, print, len, re.sub, "\n".join.
    assert unresolved == 5


def test_local_and_imported_names_are_exact_and_unbound_unique_names_inferred() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/util.py": "def helper(): ...\ndef other(): ...\n",
            "pkg/use.py": """
                from pkg.util import other

                def local(): ...

                def f():
                    local()
                    other()
                    local()

                def g():
                    from pkg.util import helper
                    helper()

                def h():
                    helper()  # not imported here, but the only function named helper
            """,
        }
    )

    assert calls(edges, "lib") == {
        ("pkg.use.f", "pkg.use.local", "exact"),
        ("pkg.use.f", "pkg.util.other", "exact"),
        ("pkg.use.g", "pkg.util.helper", "exact"),  # function-level import
        ("pkg.use.h", "pkg.util.helper", "inferred"),
    }
    local_edge = next(edge for edge in edges if edge.target == "lib:pkg.use.local")
    assert local_edge.line == 7  # one edge per caller and callee, at the first call site
    assert len(edges) == 4
    assert unresolved == 0


def test_self_cls_super_and_class_attribute_calls() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/base.py": """
                class Base:
                    def __init__(self): ...
                    def save(self): ...
                    def run(self):
                        self.save()
            """,
            "pkg/use.py": """
                from pkg.base import Base

                class Child(Base):
                    def save(self):
                        super().save()
                        self.log()
                    def log(self): ...
                    @classmethod
                    def make(cls):
                        return cls()
                    def other(self):
                        self.run()
                        Base.save(self)
                        Child.log(self)
            """,
        }
    )

    assert calls(edges, "lib") == {
        ("pkg.base.Base.run", "pkg.base.Base.save", "exact"),  # static: the class it is in
        ("pkg.use.Child.save", "pkg.base.Base.save", "exact"),  # super() starts at the bases
        ("pkg.use.Child.save", "pkg.use.Child.log", "exact"),
        ("pkg.use.Child.make", "pkg.base.Base.__init__", "exact"),  # cls() through bases
        ("pkg.use.Child.other", "pkg.base.Base.run", "exact"),  # inherited method
        ("pkg.use.Child.other", "pkg.base.Base.save", "exact"),  # C.m()
        ("pkg.use.Child.other", "pkg.use.Child.log", "exact"),
    }
    assert unresolved == 0


def test_method_lookup_terminates_on_a_cycle_in_the_bases() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": """
                class A(B):
                    def run(self):
                        self.missing()
                class B(A): ...
            """,
        }
    )

    assert edges == []
    assert unresolved == 1


def test_module_alias_calls_are_exact() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/sub/__init__.py": "",
            "pkg/sub/deep.py": "def run(): ...\n",
            "pkg/tools.py": "def go(): ...\ndef stop(): ...\n",
            "pkg/use.py": """
                import pkg.sub.deep
                from pkg import tools
                import pkg.tools as t

                def f():
                    tools.go()
                    t.stop()  # its own callee, so a broken `as` alias cannot hide behind go
                    pkg.sub.deep.run()
                    tools.missing()
            """,
        }
    )

    assert calls(edges, "lib") == {
        ("pkg.use.f", "pkg.tools.go", "exact"),
        ("pkg.use.f", "pkg.tools.stop", "exact"),
        ("pkg.use.f", "pkg.sub.deep.run", "exact"),
    }
    assert unresolved == 1  # tools.missing


def test_ambiguous_dunder_and_locally_bound_names_give_no_edge() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": """
                class A:
                    def get(self): ...
                    def __enter__(self): ...
                def callback(): ...
            """,
            "pkg/b.py": """
                class B:
                    def get(self): ...
            """,
            "pkg/use.py": """
                def f(thing, callback):
                    thing.get()  # two methods named get
                    thing.__enter__()  # dunder names are never inferred
                    callback()  # a parameter, not the module-level callback in pkg.a
                    def inner(): ...
                    inner()  # a nested def has no node
            """,
        }
    )

    assert edges == []
    assert unresolved == 4


def test_names_of_builtin_type_methods_are_never_inferred() -> None:
    # add, pop and encode are almost always set, dict and str methods, not the one function
    # in the codebase that shares the name. A call reached by an exact rule still resolves.
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/bag.py": """
                class Bag:
                    def add(self, item): ...
                    def pop(self): ...
                    def encode(self): ...
                    def fill(self, item):
                        self.add(item)
            """,
            "pkg/use.py": """
                def f(session, data, text):
                    session.add(data)
                    data.pop("key")
                    text.encode()
            """,
        }
    )

    assert calls(edges, "lib") == {("pkg.bag.Bag.fill", "pkg.bag.Bag.add", "exact")}
    assert unresolved == 3


def test_external_builtin_and_literal_calls_are_not_counted() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/use.py": """
                import json
                from os.path import join

                def f(items):
                    json.dumps(items)
                    join("a", "b")
                    len(items)
                    ", ".join(items)
                    json.loads("[]").copy()
                    [1, 2].count(1)
                    {"a": 1}.get("a")
            """,
        }
    )

    assert edges == []
    assert unresolved == 0


def test_only_function_bodies_count_and_nested_code_belongs_to_the_enclosing_function() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/use.py": """
                def deco():
                    return lambda fn: fn

                def default(): ...

                def only_default(): ...

                def target(): ...

                deco(target)  # module level: no caller

                class K:
                    value = default()  # class body: no caller

                @deco()
                def f(x=only_default()):  # decorator and default: evaluated outside f
                    def inner():
                        target()
                    key = lambda: target()
                    class Local:
                        def m(self):
                            default()
                    return inner, key, Local
            """,
        }
    )

    assert calls(edges, "lib") == {
        ("pkg.use.f", "pkg.use.target", "exact"),
        ("pkg.use.f", "pkg.use.default", "exact"),
    }
    assert unresolved == 0


def test_exact_wins_over_inferred_for_the_same_pair() -> None:
    edges, _ = link(
        {
            "pkg/__init__.py": "",
            "pkg/util.py": "def helper(): ...\n",
            "pkg/use.py": """
                from pkg import util

                def f(obj):
                    obj.helper()
                    util.helper()
            """,
        }
    )

    assert [(edge.target, edge.confidence, edge.line) for edge in edges] == [
        ("lib:pkg.util.helper", "exact", 5)  # first call site's line, best confidence
    ]


def test_index_code_adds_calls_and_records_unresolved_calls() -> None:
    batch = index_code(REGISTRY.get("layered_app"))
    ids = {node.id for node in batch.nodes}
    call_edges = [edge for edge in batch.edges if edge.kind == "CALLS"]

    assert len(call_edges) == 14
    assert all(edge.source in ids and edge.target in ids for edge in call_edges)
    assert batch.stats.unresolved_calls == 5


def test_parameters_of_nested_defs_and_lambdas_are_local() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": """
                def callback(): ...
                def fn(): ...

                def f():
                    def inner(callback):
                        callback()  # the parameter, not pkg.a.callback
                    return inner, lambda fn: fn()
            """,
        }
    )

    assert edges == []
    assert unresolved == 2


def test_names_bound_only_in_a_nested_scope_do_not_shadow_the_outer_function() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": """
                def render(): ...

                def f():
                    def inner():
                        render = 1
                        return render
                    render()
                    return inner
            """,
        }
    )

    assert calls(edges, "lib") == {("pkg.a.f", "pkg.a.render", "exact")}
    assert unresolved == 0


def test_self_of_a_class_defined_inside_a_method_is_not_the_outer_self() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": """
                class Outer:
                    def save(self): ...
                    def build(self):
                        class Local:
                            def save(self): ...
                            def run(self):
                                self.save()  # Local's self: Local has no node
                        return Local

                class Other:
                    def save(self): ...  # so `save` is not unique either
            """,
        }
    )

    assert edges == []
    assert unresolved == 1


def test_super_without_an_in_codebase_match() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": """
                import json

                class Enc(json.JSONEncoder):
                    def default(self, o):
                        return super().default(o)  # the outside base's method

                class MyError(Exception):
                    def __init__(self, message):
                        super().__init__(message)  # a builtin base

                class Base: ...

                class Child(Base):
                    def run(self):
                        super().helper()  # every base is in the codebase: unresolved

                def helper(): ...  # unique, but super() calls are never inferred
            """,
        }
    )

    assert edges == []
    assert unresolved == 1


def test_an_outside_name_reexported_by_a_codebase_module_is_external() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/compat.py": "from json import dumps\n",
            "pkg/other.py": "def dumps(): ...\n",
            "pkg/use.py": """
                from pkg.compat import dumps

                def f(data):
                    dumps(data)  # json.dumps, not the unique pkg.other.dumps
            """,
        }
    )

    assert edges == []
    assert unresolved == 0


def test_a_class_named_after_its_base_looks_up_methods_in_that_base() -> None:
    edges, _ = link(
        {
            "pkg/__init__.py": "",
            "pkg/base.py": """
                class Base:
                    def save(self): ...
            """,
            "pkg/a.py": """
                from pkg.base import Base

                class Base(Base):
                    def run(self):
                        self.save()
            """,
        }
    )

    assert calls(edges, "lib") == {("pkg.a.Base.run", "pkg.base.Base.save", "exact")}


def test_super_in_a_local_class_is_never_resolved_through_the_outer_class() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": """
                def helper(): ...

                class Base:
                    def save(self): ...

                def make():
                    class Local(Base):
                        def run(self):
                            super().helper()  # no class node: never inferred

                class Outer(Base):
                    def build(self):
                        class Local:
                            def save(self):
                                super().save()  # Local's super, not Outer's
            """,
        }
    )

    assert edges == []
    assert unresolved == 2


def test_super_with_an_explicit_class_starts_after_that_class() -> None:
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": """
                class A:
                    def m(self): ...

                class B(A):
                    def m(self): ...

                class C(B):
                    def m(self):
                        super(B, self).m()
                    def n(self):
                        super(C, self).m()
            """,
        }
    )

    assert calls(edges, "lib") == {
        ("pkg.a.C.m", "pkg.a.A.m", "exact"),
        ("pkg.a.C.n", "pkg.a.B.m", "exact"),
    }
    assert unresolved == 0


def test_a_name_the_module_binds_is_never_inferred() -> None:
    # Bound, but not to a function the resolver can place: unresolved, not a guess.
    edges, unresolved = link(
        {
            "pkg/__init__.py": "",
            "pkg/compat.py": """
                import json

                dumps = json.dumps
            """,
            "pkg/other.py": "def dumps(): ...\ndef handler(): ...\n",
            "pkg/use.py": """
                from pkg.compat import dumps

                handler = make_handler()

                def f(data):
                    dumps(data)
                    handler()
            """,
        }
    )

    assert edges == []
    assert unresolved == 2
