from pathlib import Path

import pytest

from memex.config import Codebase, load_config
from memex.ingest.code.walker import WalkerError, walk

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGISTRY = load_config(FIXTURES / "memex.toml")


def test_layered_app_yields_every_module_in_path_order() -> None:
    files = walk(REGISTRY.get("layered_app"))

    assert [(file.path, file.qualname) for file in files] == [
        ("app/__init__.py", "app"),
        ("app/__version__.py", "app.__version__"),
        ("app/_base/__init__.py", "app._base"),
        ("app/_base/service.py", "app._base.service"),
        ("app/db/__init__.py", "app.db"),
        ("app/db/models/__init__.py", "app.db.models"),
        ("app/db/models/_model_base.py", "app.db.models._model_base"),
        ("app/db/models/orders.py", "app.db.models.orders"),
        ("app/db/models/users.py", "app.db.models.users"),
        ("app/main.py", "app.main"),
        ("app/repos/__init__.py", "app.repos"),
        ("app/repos/repository_factory.py", "app.repos.repository_factory"),
        ("app/repos/repository_orders.py", "app.repos.repository_orders"),
        ("app/repos/repository_users.py", "app.repos.repository_users"),
        ("app/routes/__init__.py", "app.routes"),
        ("app/routes/orders/__init__.py", "app.routes.orders"),
        ("app/routes/orders/api.py", "app.routes.orders.api"),
        ("app/routes/users/__init__.py", "app.routes.users"),
        ("app/routes/users/api.py", "app.routes.users.api"),
        ("app/schema/__init__.py", "app.schema"),
        ("app/schema/order.py", "app.schema.order"),
        ("app/schema/user.py", "app.schema.user"),
        ("app/services/__init__.py", "app.services"),
        ("app/services/order_services/__init__.py", "app.services.order_services"),
        (
            "app/services/order_services/order_service.py",
            "app.services.order_services.order_service",
        ),
        ("app/services/user_services/__init__.py", "app.services.user_services"),
        (
            "app/services/user_services/user_service.py",
            "app.services.user_services.user_service",
        ),
    ]
    assert {file.package for file in files} == {"app"}


def test_excluded_non_python_and_outside_files_are_skipped() -> None:
    codebase = REGISTRY.get("layered_app")
    skipped = [
        "app/tests/factories.py",  # **/tests/**
        "app/migrations/env.py",  # app/migrations/**
        "app/py.typed",  # not a .py file
        "scripts/seed.py",  # outside every package
    ]
    assert all((codebase.root / path).is_file() for path in skipped)

    walked = {file.path for file in walk(codebase)}

    assert walked.isdisjoint(skipped)


def test_module_names_start_at_the_package_directory() -> None:
    files = walk(REGISTRY.get("plainrepo"))

    assert [(file.path, file.qualname, file.package) for file in files] == [
        ("reporter/__init__.py", "reporter", "reporter"),
        ("reporter/cli.py", "reporter.cli", "reporter"),
        # reporter/formats has no __init__.py; its modules are still walked.
        ("reporter/formats/table.py", "reporter.formats.table", "reporter"),
        ("src/toolkit/__init__.py", "toolkit", "src/toolkit"),
        ("src/toolkit/_client.py", "toolkit._client", "src/toolkit"),
        ("src/toolkit/_transport/__init__.py", "toolkit._transport", "src/toolkit"),
        ("src/toolkit/_transport/base.py", "toolkit._transport.base", "src/toolkit"),
        ("src/toolkit/_transport/http.py", "toolkit._transport.http", "src/toolkit"),
        ("src/toolkit/text/__init__.py", "toolkit.text", "src/toolkit"),
        ("src/toolkit/text/slug.py", "toolkit.text.slug", "src/toolkit"),
    ]


def test_missing_package_directory_is_an_error(tmp_path: Path) -> None:
    config = tmp_path / "memex.toml"
    config.write_text('[codebases.lib]\nroot = "."\npackages = ["src/lib"]\n', encoding="utf-8")

    with pytest.raises(WalkerError, match="src/lib"):
        walk(load_config(config).get("lib"))


def make_codebase(tmp_path: Path, packages: list[str], files: list[str]) -> Codebase:
    for file in files:
        (tmp_path / file).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / file).write_text("", encoding="utf-8")
    config = tmp_path / "memex.toml"
    listed = ", ".join(f'"{package}"' for package in packages)
    config.write_text(f'[codebases.lib]\nroot = "."\npackages = [{listed}]\n', encoding="utf-8")
    return load_config(config).get("lib")


@pytest.mark.parametrize("packages", [["app", "app/sub"], ["app/sub", "app"], ["app", "app/"]])
def test_overlapping_packages_are_an_error(tmp_path: Path, packages: list[str]) -> None:
    codebase = make_codebase(tmp_path, packages, ["app/__init__.py", "app/sub/__init__.py"])

    with pytest.raises(WalkerError, match="overlap"):
        walk(codebase)


def test_two_packages_with_the_same_name_are_an_error(tmp_path: Path) -> None:
    codebase = make_codebase(
        tmp_path, ["a/common", "b/common"], ["a/common/__init__.py", "b/common/__init__.py"]
    )

    with pytest.raises(WalkerError, match="common"):
        walk(codebase)


def test_package_wins_over_a_module_of_the_same_name(tmp_path: Path) -> None:
    codebase = make_codebase(
        tmp_path, ["pkg"], ["pkg/__init__.py", "pkg/a.py", "pkg/a/__init__.py", "pkg/a/b.py"]
    )

    assert [(file.path, file.qualname) for file in walk(codebase)] == [
        ("pkg/__init__.py", "pkg"),
        ("pkg/a/__init__.py", "pkg.a"),
        ("pkg/a/b.py", "pkg.a.b"),
    ]
