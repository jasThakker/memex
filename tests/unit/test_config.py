from pathlib import Path

import pytest

from memex.config import ConfigError, UnknownCodebaseError, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "memex.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_minimal_entry_gets_no_rule_defaults(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[codebases.lib]\nroot = "src/lib"\npackages = ["lib"]\n')

    codebase = load_config(path).get("lib")

    assert codebase.name == "lib"
    assert codebase.packages == ("lib",)
    assert codebase.exclude == ()
    assert codebase.docs == ()
    assert codebase.extractors == ()
    assert codebase.layers == {}
    assert codebase.doc_kinds == {}
    assert codebase.domains.strip_prefixes == ()
    assert codebase.domains.strip_suffixes == ()
    assert codebase.domains.singularize is False
    assert codebase.source is None
    assert not codebase.is_external


def test_root_is_resolved_relative_to_the_config_file(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[codebases.lib]\nroot = "vendor/lib"\npackages = ["lib"]\n')

    assert load_config(path).get("lib").root == (tmp_path / "vendor" / "lib").resolve()


def test_full_entry_keeps_rules(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        f"""
[codebases.app]
root = "."
source = "https://example.com/app.git"
ref = "v1.0"
commit = "{COMMIT}"
packages = ["app"]
exclude = ["app/migrations/**"]
docs = ["README.md"]
extractors = ["sqlalchemy"]

[codebases.app.layers]
"db/models" = "db_models"

[codebases.app.domains]
strip_suffixes = ["_services"]
singularize = true

[codebases.app.doc_kinds]
"README.md" = "readme"
""",
    )

    codebase = load_config(path).get("app")

    assert codebase.is_external
    assert codebase.layers == {"db/models": "db_models"}
    assert codebase.domains.strip_suffixes == ("_services",)
    assert codebase.domains.singularize is True
    assert codebase.doc_kinds == {"README.md": "readme"}
    assert codebase.extractors == ("sqlalchemy",)


@pytest.mark.parametrize(
    "entry",
    [
        'packages = ["lib"]',  # missing root
        'root = "."',  # missing packages
        'root = "."\npackages = []',  # empty packages
    ],
)
def test_required_fields_are_enforced(tmp_path: Path, entry: str) -> None:
    path = write_config(tmp_path, f"[codebases.lib]\n{entry}\n")

    with pytest.raises(ConfigError, match="lib"):
        load_config(path)


@pytest.mark.parametrize(
    "extra",
    [
        'exlcude = ["x"]',  # typo at codebase level
        "[codebases.lib.domains]\nsingularise = true",  # typo in a nested table
    ],
)
def test_unknown_keys_are_rejected(tmp_path: Path, extra: str) -> None:
    path = write_config(tmp_path, f'[codebases.lib]\nroot = "."\npackages = ["lib"]\n{extra}\n')

    with pytest.raises(ConfigError):
        load_config(path)


def test_unknown_top_level_key_is_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[codebase.lib]\nroot = "."\npackages = ["lib"]\n')

    with pytest.raises(ConfigError, match="codebase"):
        load_config(path)


@pytest.mark.parametrize(
    "pinning",
    [
        'source = "https://example.com/lib.git"',
        'source = "https://example.com/lib.git"\nref = "v1"',
        f'ref = "v1"\ncommit = "{COMMIT}"',
    ],
)
def test_source_ref_and_commit_must_be_set_together(tmp_path: Path, pinning: str) -> None:
    path = write_config(tmp_path, f'[codebases.lib]\nroot = "."\npackages = ["lib"]\n{pinning}\n')

    with pytest.raises(ConfigError, match="source, ref and commit"):
        load_config(path)


def test_commit_must_be_a_full_sha(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        '[codebases.lib]\nroot = "."\npackages = ["lib"]\n'
        'source = "https://example.com/lib.git"\nref = "v1"\ncommit = "abc123"\n',
    )

    with pytest.raises(ConfigError, match="commit"):
        load_config(path)


def test_invalid_toml_raises_config_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, "[codebases.lib\n")

    with pytest.raises(ConfigError, match="memex.toml"):
        load_config(path)


def test_external_lists_only_entries_with_a_source(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        f"""
[codebases.local]
root = "."
packages = ["local"]

[codebases.remote]
root = "vendor/remote"
packages = ["remote"]
source = "https://example.com/remote.git"
ref = "v1"
commit = "{COMMIT}"
""",
    )

    assert [codebase.name for codebase in load_config(path).external()] == ["remote"]


def test_unknown_codebase_error_lists_registered_names(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        '[codebases.alpha]\nroot = "."\npackages = ["a"]\n'
        '[codebases.beta]\nroot = "."\npackages = ["b"]\n',
    )

    with pytest.raises(UnknownCodebaseError, match="alpha, beta"):
        load_config(path).get("gamma")


def test_repo_config_loads() -> None:
    registry = load_config(REPO_ROOT / "memex.toml")

    assert sorted(registry.names()) == ["httpx", "mealie", "memex"]
    assert sorted(codebase.name for codebase in registry.external()) == ["httpx", "mealie"]
    assert registry.get("memex").root == REPO_ROOT
    assert registry.get("httpx").extractors == ()
    assert registry.get("httpx").layers == {}
