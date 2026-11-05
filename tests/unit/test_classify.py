from pathlib import Path

import pytest

from memex.config import Codebase, DomainRules, load_config
from memex.ingest.code.classify import classify, normalize_domain, singularize
from memex.ingest.code.walker import walk

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGISTRY = load_config(FIXTURES / "memex.toml")
LAYERED_APP = REGISTRY.get("layered_app")
NO_RULES = LAYERED_APP.model_copy(update={"layers": {}, "domains": DomainRules()})


def labels(codebase: Codebase) -> dict[str, tuple[str, str | None]]:
    return {source.path: classify(codebase, source) for source in walk(codebase)}


def test_plainrepo_gets_default_labels_from_its_folders() -> None:
    assert labels(REGISTRY.get("plainrepo")) == {
        "reporter/__init__.py": ("root", None),
        "reporter/cli.py": ("root", "cli"),
        "reporter/formats/table.py": ("formats", "table"),
        "src/toolkit/__init__.py": ("root", None),
        "src/toolkit/_client.py": ("root", "client"),  # one leading underscore dropped
        "src/toolkit/_transport/__init__.py": ("transport", None),
        "src/toolkit/_transport/base.py": ("transport", "base"),
        "src/toolkit/_transport/http.py": ("transport", "http"),
        "src/toolkit/text/__init__.py": ("text", None),
        "src/toolkit/text/slug.py": ("text", "slug"),
    }


def test_layered_app_with_rules_aligns_domains_across_layers() -> None:
    assert labels(LAYERED_APP) == {
        "app/__init__.py": ("root", None),
        "app/__version__.py": ("root", "version"),  # dunder: both underscore pairs dropped
        "app/main.py": ("root", "main"),
        "app/_base/__init__.py": ("base", None),  # not in the layer map: default rule
        "app/_base/service.py": ("base", "service"),
        "app/db/__init__.py": ("db", None),  # "db" alone is not a layer key
        "app/db/models/__init__.py": ("db_models", None),
        "app/db/models/_model_base.py": ("db_models", "model_base"),
        "app/db/models/orders.py": ("db_models", "order"),
        "app/db/models/users.py": ("db_models", "user"),
        "app/repos/__init__.py": ("repos", None),
        "app/repos/repository_factory.py": ("repos", "factory"),
        "app/repos/repository_orders.py": ("repos", "order"),
        "app/repos/repository_users.py": ("repos", "user"),
        "app/routes/__init__.py": ("routes", None),
        "app/routes/orders/__init__.py": ("routes", "order"),
        "app/routes/orders/api.py": ("routes", "order"),
        "app/routes/users/__init__.py": ("routes", "user"),
        "app/routes/users/api.py": ("routes", "user"),
        "app/schema/__init__.py": ("schema", None),
        "app/schema/order.py": ("schema", "order"),
        "app/schema/user.py": ("schema", "user"),
        "app/services/__init__.py": ("services", None),
        "app/services/order_services/__init__.py": ("services", "order"),
        "app/services/order_services/order_service.py": ("services", "order"),
        "app/services/user_services/__init__.py": ("services", "user"),
        "app/services/user_services/user_service.py": ("services", "user"),
    }


def test_same_paths_without_rules_keep_raw_folder_and_file_names() -> None:
    raw = labels(NO_RULES)

    assert raw["app/db/models/users.py"] == ("db", "models")
    assert raw["app/repos/repository_orders.py"] == ("repos", "repository_orders")
    assert raw["app/services/user_services/user_service.py"] == ("services", "user_services")
    assert raw["app/routes/users/api.py"] == ("routes", "users")
    assert raw["app/__version__.py"] == ("root", "version")


def test_domain_is_the_folder_right_under_the_layer_however_deep_the_file(
    tmp_path: Path,
) -> None:
    deep = walk_one(tmp_path, {}, "pkg/ingest/code/extractors/sql.py")
    mapped = walk_one(tmp_path, {"db/models": "db_models"}, "pkg/db/models/billing/plans/x.py")

    assert deep == ("ingest", "code")
    assert mapped == ("db_models", "billing")


def test_longest_layer_key_wins(tmp_path: Path) -> None:
    layers = {"db": "database", "db/models": "db_models"}

    assert walk_one(tmp_path, layers, "pkg/db/models/users.py") == ("db_models", "users")
    assert walk_one(tmp_path, layers, "pkg/db/session.py") == ("database", "session")
    assert walk_one(tmp_path, layers, "pkg/dbtools/x.py") == ("dbtools", "x")  # whole folders


def walk_one(tmp_path: Path, layers: dict[str, str], path: str) -> tuple[str, str | None]:
    """Labels for one file in a fresh one-package codebase with the given layer map."""
    root = tmp_path / str(len(list(tmp_path.iterdir())))
    (root / path).parent.mkdir(parents=True)
    (root / path).write_text("", encoding="utf-8")
    codebase = Codebase(name="lib", root=root, packages=("pkg",), layers=layers)
    [source] = walk(codebase)
    return classify(codebase, source)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("_private", "private"),  # one leading underscore dropped
        ("__dunder__", "dunder"),
        ("repository_orders", "order"),  # prefix, then singularize
        ("user_services", "user"),  # suffix, then singularize
        ("order_service", "order"),
        ("repository_user_services", "user"),  # prefix and suffix
        ("_repository_users", "user"),  # underscore drop comes first
        ("repository_", "repository_"),  # never strip a name down to nothing
    ],
)
def test_domain_rules_apply_in_order(name: str, expected: str) -> None:
    rules = DomainRules(
        strip_prefixes=("repository_", "repo_"),
        strip_suffixes=("_services", "_service"),
        singularize=True,
    )

    assert normalize_domain(name, rules) == expected


def test_only_the_first_matching_prefix_and_suffix_are_stripped() -> None:
    rules = DomainRules(strip_prefixes=("a_", "a_b_"), strip_suffixes=("_y", "_x_y"))

    assert normalize_domain("a_b_c_x_y", rules) == "b_c_x"


def test_without_rules_only_underscores_change() -> None:
    assert normalize_domain("_user_services", DomainRules()) == "user_services"


@pytest.mark.parametrize(
    "word, expected",
    [
        ("users", "user"),
        ("categories", "category"),
        ("status", "status"),  # -s after u
        ("address", "address"),  # -s after s
        ("analysis", "analysis"),  # -s after i
        ("analytics", "analytics"),  # -ics kept
        ("user", "user"),
    ],
)
def test_singularize(word: str, expected: str) -> None:
    assert singularize(word) == expected
