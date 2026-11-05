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
    """Every .py file under the codebase's packages, minus `exclude`, sorted by path.

    A module `x.py` next to a package `x/__init__.py` is skipped: Python imports the package.
    So is any file whose name, or a folder above it in the package, is not a Python
    identifier (`foo.bar.py`, `my-dir/`, `2024_init.py`): it cannot be imported as a module.
    """
    _check_packages(codebase)
    files: list[SourceFile] = []
    for package in codebase.packages:
        package_dir = codebase.root / package
        for file in package_dir.rglob("*.py"):
            path = PurePosixPath(file.relative_to(codebase.root).as_posix())
            if (
                not file.is_file()
                or _is_excluded(path, codebase.exclude)
                or (file.with_suffix("") / "__init__.py").is_file()
                or not _is_importable(file.relative_to(package_dir))
            ):
                continue
            qualname = _qualname(package_dir.name, file.relative_to(package_dir))
            files.append(SourceFile(path=str(path), qualname=qualname, package=package))
    return sorted(files, key=lambda file: file.path)


def _check_packages(codebase: Codebase) -> None:
    """Every package is a directory, no package lies inside another, and names are unique."""
    seen: dict[PurePosixPath, str] = {}
    for package in codebase.packages:
        if not (codebase.root / package).is_dir():
            raise WalkerError(
                f"codebase {codebase.name!r}: package directory {package!r} "
                f"not found under {codebase.root}"
            )
        path = PurePosixPath(package)
        for other_path, other in seen.items():
            if path.is_relative_to(other_path) or other_path.is_relative_to(path):
                raise WalkerError(
                    f"codebase {codebase.name!r}: packages {other!r} and {package!r} overlap"
                )
            if path.name == other_path.name:
                raise WalkerError(
                    f"codebase {codebase.name!r}: packages {other!r} and {package!r} "
                    f"would both be named {path.name!r}"
                )
        seen[path] = package


def _is_excluded(path: PurePosixPath, patterns: tuple[str, ...]) -> bool:
    return any(path.full_match(pattern) for pattern in patterns)


def _is_importable(relative: Path) -> bool:
    return all(part.isidentifier() for part in relative.with_suffix("").parts)


def _qualname(package_name: str, relative: Path) -> str:
    parts = relative.with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join((package_name, *parts))
