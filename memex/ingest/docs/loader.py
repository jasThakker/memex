"""Find and read a codebase's Markdown docs.

`docs` globs are expanded under the codebase root; only `.md` files count, each file is read
once, and the result is sorted by path. A glob that matches no Markdown file is a ConfigError,
so a typo in memex.toml fails loudly. `exclude` applies to code only. A doc's kind is the
label of the first `doc_kinds` glob that matches its path, in table order, or `doc`.
See DESIGN.md section 5.
"""

from dataclasses import dataclass
from pathlib import PurePosixPath

from memex.config import Codebase, ConfigError
from memex.graph.model import ParseError

DEFAULT_KIND = "doc"


@dataclass(frozen=True, kw_only=True)
class DocFile:
    path: str  # relative to the codebase root, forward slashes
    kind: str
    text: str


def load_docs(codebase: Codebase) -> tuple[list[DocFile], list[ParseError]]:
    """Every doc file with its kind and text, plus a ParseError for each unreadable one."""
    files: list[DocFile] = []
    errors: list[ParseError] = []
    for path in _doc_paths(codebase):
        try:
            text = (codebase.root / path).read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as error:
            errors.append(ParseError(path=path, line=None, message=f"not UTF-8: {error}"))
            continue
        files.append(DocFile(path=path, kind=doc_kind(codebase, path), text=text))
    return files, errors


def doc_kind(codebase: Codebase, path: str) -> str:
    relative = PurePosixPath(path)
    for pattern, kind in codebase.doc_kinds.items():
        if relative.full_match(pattern):
            return kind
    return DEFAULT_KIND


def _doc_paths(codebase: Codebase) -> list[str]:
    paths: set[str] = set()
    for pattern in codebase.docs:
        matched = {
            found.relative_to(codebase.root).as_posix()
            for found in codebase.root.glob(pattern, case_sensitive=True)
            if found.suffix == ".md" and found.is_file()
        }
        if not matched:
            raise ConfigError(
                f"codebase {codebase.name!r}: docs glob {pattern!r} matches no Markdown "
                f"files under {codebase.root}"
            )
        paths |= matched
    return sorted(paths)
