"""USES edges (ADR-003, DESIGN.md section 9): a codebase function or class named as a value.

A name or dotted name that is read and resolves exactly gives USES, unless the reference is a
call that gives a CALLS edge. Annotations, strings, decorators, local names, builtins and
outside names never do.
"""

from collections import Counter

from parsing import REGISTRY, parse_files

from memex.ingest.code import index_code
from memex.ingest.code.resolver import SymbolTable, link_uses


def uses(files: dict[str, str]) -> set[tuple[str, str, int | None]]:
    """(source, target, line) for each USES edge, without the codebase prefix."""
    edges = link_uses("lib", SymbolTable(parse_files(files)))
    assert all(edge.kind == "USES" for edge in edges)
    return {
        (edge.source.removeprefix("lib:"), edge.target.removeprefix("lib:"), edge.line)
        for edge in edges
    }


DEPS = """
    def current_user(): ...
    def helper(): ...

    class Model:
        def save(self): ...

    class WithInit:
        def __init__(self): ...
"""


def test_functions_and_classes_passed_or_used_as_values() -> None:
    found = uses(
        {
            "pkg/__init__.py": "",
            "pkg/deps.py": DEPS,
            "pkg/use.py": """
                from pkg import deps
                from pkg.deps import Model, current_user, helper

                def register(fn): ...

                def by_argument():
                    register(helper)
                def by_module_alias():
                    register(deps.helper)
                def by_class_value(rows):
                    return [r for r in rows if isinstance(r, Model)]
                def by_method_of_a_class():
                    return Model.save
                def by_chained_call_on_a_class():
                    return Model.query.filter()
                def by_construction_without_init():
                    return Model()
                def in_a_lambda():
                    return lambda: current_user
            """,
        }
    )

    use = "pkg.use"
    assert found == {
        (f"{use}.by_argument", "pkg.deps.helper", 8),
        (f"{use}.by_module_alias", "pkg.deps.helper", 10),
        (f"{use}.by_class_value", "pkg.deps.Model", 12),
        (f"{use}.by_method_of_a_class", "pkg.deps.Model.save", 14),  # the longest that resolves
        (f"{use}.by_chained_call_on_a_class", "pkg.deps.Model", 16),  # Model.query: no node
        (f"{use}.by_construction_without_init", "pkg.deps.Model", 18),  # no CALLS edge
        (f"{use}.in_a_lambda", "pkg.deps.current_user", 20),
    }


def test_parameter_defaults_and_class_bodies_count() -> None:
    found = uses(
        {
            "pkg/__init__.py": "",
            "pkg/deps.py": DEPS,
            "pkg/use.py": """
                from fastapi import Depends
                from pkg.deps import Model, current_user, helper

                def route(user=Depends(current_user), *, extra=helper): ...

                class Controller:
                    user: Model = Depends(current_user)
                    fallback = helper

                    def method(self): ...
            """,
        }
    )

    assert found == {
        ("pkg.use.route", "pkg.deps.current_user", 5),
        ("pkg.use.route", "pkg.deps.helper", 5),
        ("pkg.use.Controller", "pkg.deps.current_user", 8),  # the value, not the annotation
        ("pkg.use.Controller", "pkg.deps.helper", 9),
    }


def test_methods_named_through_self_and_typed_attributes() -> None:
    found = uses(
        {
            "pkg/__init__.py": "",
            "pkg/deps.py": DEPS,
            "pkg/use.py": """
                from pkg.deps import Model

                def schedule(fn): ...

                class Worker:
                    def __init__(self, model: Model) -> None:
                        self.model = model
                    def work(self): ...
                    def start(self):
                        schedule(self.work)
                        schedule(self.model.save)
                        schedule(self.model.missing)
            """,
        }
    )

    assert found == {
        ("pkg.use.Worker.start", "pkg.use.Worker.work", 11),
        ("pkg.use.Worker.start", "pkg.deps.Model.save", 12),
    }


def test_calls_annotations_and_unresolvable_names_give_no_uses() -> None:
    found = uses(
        {
            "pkg/__init__.py": "",
            "pkg/deps.py": DEPS,
            "pkg/use.py": """
                import json
                from pkg.deps import Model, WithInit, helper

                def register(fn): ...

                @register
                def decorated(): ...

                def calls_only():
                    helper()  # a call with a CALLS edge
                    WithInit()  # a class with __init__: CALLS
                    Model().save()  # Model() is a use; .save() is a call on it

                def annotated(m: Model, name: "Model" = "helper") -> Model:
                    x: Model = 1
                    return x

                def local_and_outside(helper):
                    register(helper)  # the parameter, not pkg.deps.helper
                    register(json.dumps)  # outside the codebase
                    register(len)  # builtin

                def recursive():
                    register(recursive)  # itself

                def repeated():
                    register(helper)
                    register(helper)
            """,
        }
    )

    assert found == {
        ("pkg.use.calls_only", "pkg.deps.Model", 13),
        ("pkg.use.repeated", "pkg.deps.helper", 28),  # one edge per pair: the first line
    }


def test_layered_app_uses_and_no_duplicate_of_references() -> None:
    batch = index_code(REGISTRY.get("layered_app"))
    found = {
        (edge.source.removeprefix("layered_app:"), edge.target.removeprefix("layered_app:"))
        for edge in batch.edges
        if edge.kind == "USES"
    }

    # Schemas, ORM models and the repositories have no __init__ in the codebase, so
    # constructing them is a use.
    factory_init = "app.repos.repository_factory.AllRepositories.__init__"
    assert found == {
        (factory_init, "app.repos.repository_users.UserRepository"),
        (factory_init, "app.repos.repository_orders.OrderRepository"),
        ("app.services.order_services.order_service.OrderService.get", "app.schema.order.OrderOut"),
        ("app.services.user_services.user_service.UserService.get", "app.schema.user.UserOut"),
        ("app.repos.repository_orders.OrderRepository.get_one", "app.db.models.orders.Order"),
        ("app.repos.repository_users.UserRepository.get_one", "app.db.models.users.User"),
    }
    # Order's `relationship(User)` is a REFERENCES edge, so it is not also a USES edge.
    references = {(e.source, e.target) for e in batch.edges if e.kind == "REFERENCES"}
    assert not references & {(e.source, e.target) for e in batch.edges if e.kind == "USES"}
    assert Counter(edge.kind for edge in batch.edges)["USES"] == 6
