"""Opt-in framework extractors. A codebase picks them by name with `extractors` in memex.toml.

Adding one means a new module here and one line in EXTRACTORS (DESIGN.md section 6).
"""

from memex.ingest.code.extractors.base import Extractor
from memex.ingest.code.extractors.sqlalchemy import SqlAlchemyExtractor

EXTRACTORS: dict[str, type[Extractor]] = {
    SqlAlchemyExtractor.name: SqlAlchemyExtractor,
}
