"""The interface every framework extractor implements (DESIGN.md section 6).

An extractor reads parsed modules through the read-only SymbolTable and returns edges between
nodes that already exist. It never creates nodes or touches the database. It may also return
values for class properties the graph model declares for this purpose (CLASS_PROPERTIES).
"""

from collections.abc import Mapping, Sequence
from typing import ClassVar, Protocol

from memex.graph.model import Edge
from memex.ingest.code.parser import ParsedModule
from memex.ingest.code.resolver import SymbolTable

CLASS_PROPERTIES = frozenset({"tablename"})  # ClassNode fields an extractor may set


class Extractor(Protocol):
    name: ClassVar[str]

    def extract(self, modules: Sequence[ParsedModule], symbols: SymbolTable) -> list[Edge]:
        """New edges, typically REFERENCES with `extractor` set to this extractor's name."""
        ...

    def class_properties(
        self, modules: Sequence[ParsedModule], symbols: SymbolTable
    ) -> Mapping[str, Mapping[str, str]]:
        """Class id -> {property: value}, for properties in CLASS_PROPERTIES."""
        ...
