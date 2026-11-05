"""Find the Python modules of a codebase and give each its dotted name.

Each `packages` entry is a directory relative to the codebase root. Module names start at
that directory's own name, so `src/pkg/a.py` is `pkg.a` and `src/pkg/__init__.py` is `pkg`.
`exclude` globs are matched against paths relative to the root. See DESIGN.md section 5.
"""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from memex.config import Codebase


class WalkerError(Exception):
    """A `packages` entry does not point at a directory."""


@dataclass(frozen=True)
class SourceFile:
    path: str  # relative to the codebase root, forward slashes
    qualname: str
    package: str  # the `packages` entry this file belongs to


def walk(codebase: Codebase) -> list[SourceFile]:
    """Every .py file under the codebase's packages, minus `exclude`, sorted by path."""
    files: list[SourceFile] = []
    for package in codebase.packages:
        package_dir = codebase.root / package
        if not package_dir.is_dir():
            raise WalkerError(
                f"codebase {codebase.name!r}: package directory {package!r} "
                f"not found under {codebase.root}"
            )
        for file in package_dir.rglob("*.py"):
            path = PurePosixPath(file.relative_to(codebase.root).as_posix())
            if not file.is_file() or _is_excluded(path, codebase.exclude):
                continue
            qualname = _qualname(package_dir.name, file.relative_to(package_dir))
            files.append(SourceFile(path=str(path), qualname=qualname, package=package))
    return sorted(files, key=lambda file: file.path)


def _is_excluded(path: PurePosixPath, patterns: tuple[str, ...]) -> bool:
    return any(path.full_match(pattern) for pattern in patterns)


def _qualname(package_name: str, relative: Path) -> str:
    parts = relative.with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join((package_name, *parts))
