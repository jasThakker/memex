"""Tests for scripts/fetch_codebases.py, run as a subprocess against a tiny local git repo."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fetch_codebases.py"
GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@example.com"]
GIT += ["-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


@pytest.fixture
def origin(tmp_path: Path) -> tuple[Path, str]:
    """A git repo with one commit tagged v1. Returns (path, commit sha)."""
    repo = tmp_path / "origin"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    git("add", "README.md", cwd=repo)
    git("commit", "-q", "-m", "first", cwd=repo)
    git("tag", "v1", cwd=repo)
    return repo, git("rev-parse", "HEAD", cwd=repo)


def write_config(tmp_path: Path, origin: Path, commit: str) -> Path:
    path = tmp_path / "memex.toml"
    path.write_text(
        f"""
[codebases.lib]
root = "vendor/lib"
packages = ["lib"]
source = "{origin.as_uri()}"
ref = "v1"
commit = "{commit}"

[codebases.local]
root = "."
packages = ["local"]
""",
        encoding="utf-8",
    )
    return path


def fetch(config: Path, *names: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(config), *names],
        capture_output=True,
        text=True,
    )


def test_clones_at_ref_and_verifies_commit(tmp_path: Path, origin: tuple[Path, str]) -> None:
    repo, commit = origin
    config = write_config(tmp_path, repo, commit)

    result = fetch(config)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "vendor" / "lib" / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert f"lib: ok at {commit}" in result.stdout


def test_skips_codebases_without_a_source(tmp_path: Path, origin: tuple[Path, str]) -> None:
    repo, commit = origin
    config = write_config(tmp_path, repo, commit)

    result = fetch(config, "local")

    assert result.returncode == 0, result.stderr
    assert "local: skipped (no source)" in result.stdout


def test_rerun_only_checks_an_existing_checkout(tmp_path: Path, origin: tuple[Path, str]) -> None:
    repo, commit = origin
    config = write_config(tmp_path, repo, commit)
    assert fetch(config).returncode == 0
    marker = tmp_path / "vendor" / "lib" / "local-marker.txt"
    marker.write_text("keep me\n", encoding="utf-8")

    result = fetch(config)

    assert result.returncode == 0, result.stderr
    assert "already present" in result.stdout
    assert marker.exists()


def test_wrong_commit_fails_and_deletes_nothing(tmp_path: Path, origin: tuple[Path, str]) -> None:
    repo, _ = origin
    config = write_config(tmp_path, repo, "f" * 40)

    result = fetch(config)

    assert result.returncode == 1
    assert "expected " + "f" * 40 in result.stderr
    assert (tmp_path / "vendor" / "lib" / "README.md").exists()


def test_existing_directory_that_is_not_a_git_repo_fails(
    tmp_path: Path, origin: tuple[Path, str]
) -> None:
    repo, commit = origin
    config = write_config(tmp_path, repo, commit)
    (tmp_path / "vendor" / "lib").mkdir(parents=True)

    result = fetch(config)

    assert result.returncode == 1
    assert "not a git checkout" in result.stderr


def test_unknown_codebase_name_lists_registered_names(
    tmp_path: Path, origin: tuple[Path, str]
) -> None:
    repo, commit = origin
    config = write_config(tmp_path, repo, commit)

    result = fetch(config, "nope")

    assert result.returncode == 2
    assert "lib, local" in result.stderr
