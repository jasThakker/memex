"""Layer and domain labels from the folder structure. See DESIGN.md section 8.

Default: the layer is the first folder under the package (files directly in the package get
layer "root"); the domain is the next folder, or the file stem for a file directly in the
layer folder or the package. An `__init__.py` is labeled as its directory, so one directly in
the package or in a layer folder gets no domain. A leading underscore is dropped from labels;
dunder names lose both pairs.

With rules: `layers` keys are folder paths under the package, matched longest first; the
domain is then the next folder (or the file stem) after the matched path. Unmatched folders
use the default. `domains` rules normalize every domain name.
"""

from pathlib import PurePosixPath

from memex.config import Codebase, DomainRules
from memex.ingest.code.walker import SourceFile

ROOT_LAYER = "root"


def classify(codebase: Codebase, source: SourceFile) -> tuple[str, str | None]:
    """(layer, domain) for one module; domain is None for some `__init__.py` files."""
    relative = PurePosixPath(source.path).relative_to(PurePosixPath(source.package))
    folders = relative.parent.parts
    is_init = relative.name == "__init__.py"

    matched = _match_layer(folders, codebase.layers)
    if matched is not None:
        layer, depth = matched
    elif folders:
        layer, depth = _drop_underscores(folders[0]), 1
    else:
        layer, depth = ROOT_LAYER, 0

    below = folders[depth:]
    if below:
        name = below[0]
    elif is_init:
        return layer, None
    else:
        name = relative.stem
    return layer, normalize_domain(name, codebase.domains)


def normalize_domain(name: str, rules: DomainRules) -> str:
    """Apply, in order: underscore dropping, first matching prefix, first matching suffix,
    singularize. A prefix or suffix that would leave nothing is not stripped."""
    name = _drop_underscores(name)
    for prefix in rules.strip_prefixes:
        if name.startswith(prefix) and len(name) > len(prefix):
            name = name.removeprefix(prefix)
            break
    for suffix in rules.strip_suffixes:
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name.removesuffix(suffix)
            break
    return singularize(name) if rules.singularize else name


def singularize(word: str) -> str:
    """`-ies` becomes `-y`; a trailing `-s` is dropped except after `s`, `u` or `i`;
    words ending in `-ics` are kept."""
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith("ics"):
        return word
    if word.endswith("s") and len(word) > 1 and word[-2] not in "sui":
        return word[:-1]
    return word


def _match_layer(folders: tuple[str, ...], layers: dict[str, str]) -> tuple[str, int] | None:
    """(label, number of folders matched) for the longest `layers` key the folders start with."""
    keys = sorted(layers, key=lambda key: len(PurePosixPath(key).parts), reverse=True)
    for key in keys:
        parts = PurePosixPath(key).parts
        if folders[: len(parts)] == parts:
            return layers[key], len(parts)
    return None


def _drop_underscores(name: str) -> str:
    if name.startswith("__") and name.endswith("__") and len(name) > 4:
        return name[2:-2]
    if name.startswith("_") and len(name) > 1:
        return name[1:]
    return name
