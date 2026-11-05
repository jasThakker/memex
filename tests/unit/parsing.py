"""Shared helpers: parse a fixture codebase, or inline modules, into ParsedModules."""

from pathlib import Path
from textwrap import dedent

from memex.config import load_config
from memex.ingest.code.parser import ParsedModule, parse_module
from memex.ingest.code.walker import SourceFile, walk

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REGISTRY = load_config(FIXTURES / "memex.toml")


def parse_codebase(name: str) -> list[ParsedModule]:
    codebase = REGISTRY.get(name)
    modules = []
    for source in walk(codebase):
        parsed = parse_module(name, source, (codebase.root / source.path).read_bytes())
        assert isinstance(parsed, ParsedModule)
        modules.append(parsed)
    return modules


def parse_files(files: dict[str, str]) -> list[ParsedModule]:
    """Parse inline modules of a codebase called `lib`, keyed by path."""
    modules = []
    for path, text in files.items():
        parts = path.removesuffix(".py").split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        source = SourceFile(path=path, qualname=".".join(parts), package=parts[0])
        parsed = parse_module("lib", source, dedent(text).encode())
        assert isinstance(parsed, ParsedModule)
        modules.append(parsed)
    return modules
