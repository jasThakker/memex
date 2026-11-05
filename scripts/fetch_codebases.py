"""Fetch the external codebases registered in memex.toml at their pinned commits.

For each codebase with a `source`: clone it at `ref` if its `root` does not exist yet,
then check that the checkout is at `commit`. An existing checkout is only checked, never
changed or deleted. Codebases without a `source` (such as Memex itself) are skipped.

Usage:
    uv run python scripts/fetch_codebases.py                 # every codebase in memex.toml
    uv run python scripts/fetch_codebases.py NAME [NAME...]  # selected codebases
    uv run python scripts/fetch_codebases.py --config path/to/memex.toml

Exit codes: 0 all ok, 1 a clone failed or a checkout is at the wrong commit, 2 bad input.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from memex.config import Codebase, ConfigError, UnknownCodebaseError, load_config

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "memex.toml"


class FetchError(Exception):
    """A codebase could not be fetched or is not at its pinned commit."""


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise FetchError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def fetch(codebase: Codebase) -> str:
    """Clone if missing, then verify the commit. Returns a one-line status."""
    if codebase.source is None or codebase.ref is None or codebase.commit is None:
        return f"{codebase.name}: skipped (no source)"

    root = codebase.root
    if root.exists():
        status = "already present"
    else:
        clone_args = ["--quiet", "--depth", "1", "--branch", codebase.ref]
        git("clone", *clone_args, codebase.source, str(root))
        status = "cloned"

    # vendor/ lives inside the Memex repo, so a plain rev-parse in a stray folder would report
    # Memex's own commit. Require root to be the top of its own git checkout.
    try:
        toplevel = Path(git("-C", str(root), "rev-parse", "--show-toplevel")).resolve()
    except FetchError:
        toplevel = None
    if toplevel != root.resolve():
        raise FetchError(f"{codebase.name}: {root} exists but is not a git checkout")

    head = git("-C", str(root), "rev-parse", "HEAD")
    if head != codebase.commit:
        raise FetchError(
            f"{codebase.name}: {root} is at {head}, expected {codebase.commit} "
            f"({codebase.ref}). Nothing was changed; remove the directory and re-run to refetch."
        )
    return f"{codebase.name}: ok at {head} ({status})"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="codebases to fetch (default: all)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)

    try:
        registry = load_config(args.config)
        selected = [registry.get(name) for name in args.names or registry.names()]
    except (ConfigError, UnknownCodebaseError) as error:
        print(error, file=sys.stderr)
        return 2

    failed = False
    for codebase in selected:
        try:
            print(fetch(codebase))
        except FetchError as error:
            print(error, file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
