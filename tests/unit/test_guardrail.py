"""Guardrail: the memex/ package must not mention any external benchmark codebase.

Memex is a general tool. Repo-specific rules belong in memex.toml and assertions about a
real repo belong in its realrepo smoke test, never in the core package.
"""

from pathlib import Path

from memex.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[2]


def find_banned_names(directory: Path, names: list[str]) -> list[tuple[Path, int, str]]:
    """Every (file, line number, name) where a banned name appears, ignoring case.

    Scans every file except bytecode caches, so comments and docstrings count too.
    Plain substring matching is deliberate: it also catches names like `acme_layout`.
    """
    lowered = [name.lower() for name in names]
    hits: list[tuple[Path, int, str]] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for number, line in enumerate(text.splitlines(), start=1):
            hits.extend((path, number, name) for name in lowered if name in line)
    return hits


def test_scanner_reports_a_planted_name_in_any_case(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "clean.py").write_text('"""Nothing to see."""\n', encoding="utf-8")
    (package / "leaky.py").write_text(
        '"""Parser."""\n# Handle the Acme repos layout\n', encoding="utf-8"
    )

    hits = find_banned_names(package, ["acme"])

    assert hits == [(package / "leaky.py", 2, "acme")]


def test_memex_package_has_no_external_benchmark_names() -> None:
    names = [codebase.name for codebase in load_config(REPO_ROOT / "memex.toml").external()]
    assert names, "no external codebases registered, so the guardrail would check nothing"

    assert find_banned_names(REPO_ROOT / "memex", names) == []
