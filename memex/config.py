"""Load memex.toml: the registry of codebases Memex can index.

Path rules: `root` is relative to the config file; `exclude`, `docs` and `doc_kinds`
globs are relative to `root`; `layers` keys are relative to each package directory.
Optional keys default to "no rules". See DESIGN.md section 5.
"""

import tomllib
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ConfigError(Exception):
    """memex.toml is missing, unreadable or invalid."""


class UnknownCodebaseError(LookupError):
    """A codebase name that is not registered in memex.toml."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DomainRules(_Strict):
    """Optional normalization applied to folder or file names when deriving domains."""

    strip_prefixes: tuple[str, ...] = ()
    strip_suffixes: tuple[str, ...] = ()
    singularize: bool = False


class Codebase(_Strict):
    """One registered codebase. `root` is absolute after loading."""

    name: str
    root: Path
    packages: tuple[str, ...] = Field(min_length=1)
    source: str | None = None
    ref: str | None = None
    commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    exclude: tuple[str, ...] = ()
    docs: tuple[str, ...] = ()
    extractors: tuple[str, ...] = ()
    layers: dict[str, str] = Field(default_factory=dict)
    domains: DomainRules = DomainRules()
    doc_kinds: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _pinning_is_all_or_nothing(self) -> Self:
        pinned = [self.source is not None, self.ref is not None, self.commit is not None]
        if any(pinned) and not all(pinned):
            raise ValueError("source, ref and commit must be set together or not at all")
        return self

    @property
    def is_external(self) -> bool:
        """True for codebases fetched from elsewhere (they have a source)."""
        return self.source is not None


class Registry(_Strict):
    """All codebases from memex.toml, keyed by name."""

    codebases: dict[str, Codebase]

    def names(self) -> list[str]:
        return list(self.codebases)

    def get(self, name: str) -> Codebase:
        try:
            return self.codebases[name]
        except KeyError:
            registered = ", ".join(sorted(self.codebases)) or "none"
            raise UnknownCodebaseError(
                f"unknown codebase {name!r}; registered codebases: {registered}"
            ) from None

    def external(self) -> list[Codebase]:
        return [codebase for codebase in self.codebases.values() if codebase.is_external]


def load_config(path: Path) -> Registry:
    """Read and validate a memex.toml file."""
    path = Path(path).resolve()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error

    unknown = set(data) - {"codebases"}
    if unknown:
        raise ConfigError(f"{path}: unknown top-level keys: {', '.join(sorted(unknown))}")

    codebases: dict[str, Codebase] = {}
    for name, entry in data.get("codebases", {}).items():
        try:
            codebases[name] = Codebase.model_validate(_prepare(name, entry, path.parent))
        except ValidationError as error:
            raise ConfigError(f"{path}: invalid codebase {name!r}:\n{error}") from error
    return Registry(codebases=codebases)


def _prepare(name: str, entry: Any, base: Path) -> Any:
    """Add the name and make `root` absolute; leave everything else to validation."""
    if not isinstance(entry, dict):
        return entry
    prepared = {**entry, "name": name}
    if isinstance(prepared.get("root"), str):
        prepared["root"] = (base / prepared["root"]).resolve()
    return prepared
