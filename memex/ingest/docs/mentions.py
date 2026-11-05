"""Link doc chunks to the code they name, lexically (DESIGN.md section 7, MENTIONS).

Three kinds of match, strongest first; a chunk gets one edge per target, with its strongest:
- `qualname`: a whole dotted name (`pkg.mod.Class`) equal to a Module, Class or Function
  qualname, anywhere in the text, code fences included.
- `path`: a path relative to the codebase root that names a module file (`pkg/mod.py`) or a
  package directory (`pkg/sub` or `pkg/sub/`). Globs and URLs are skipped.
- `backtick_name`: an inline code span outside fences holding a name, optionally with `()`.
  A bare name links only if exactly one Class or module-level Function has it and it is not
  a dunder, a keyword, a builtin or a builtin type method name. Methods need the dotted form
  (`Class.method`), because bare method names in docs are mostly ordinary words (`json`);
  modules are never matched by bare name. A dotted name links if exactly one Class or
  Function qualname ends with it.
Ambiguous or unknown names give no edge. Unbackticked bare words are never matched.
"""

import builtins
import keyword
import re
from collections import defaultdict
from collections.abc import Sequence

from memex.graph.model import ClassNode, Edge, FunctionNode, MentionMatch, ModuleNode, Node
from memex.ingest.code.resolver import _BUILTIN_METHOD_NAMES
from memex.ingest.docs.chunker import outside_fences

_QUALNAME = re.compile(r"(?<![\w./])[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
_PATH = re.compile(r"(?<![\w./:-])(?:\./)?[\w*?-][\w.*?-]*(?:/[\w.*?-]+)+/?")
_CODE_SPAN = re.compile(r"(`+)([^`\n]+?)\1(?!`)")
_NAME = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_RANK: dict[MentionMatch, int] = {"qualname": 0, "path": 1, "backtick_name": 2}
_COMMON_NAMES = frozenset(
    {*dir(builtins), *keyword.kwlist, *keyword.softkwlist, *_BUILTIN_METHOD_NAMES}
)


class MentionTargets:
    """Lookups from qualname, path, short name and dotted suffix to code node ids."""

    def __init__(self, code_nodes: Sequence[Node]) -> None:
        self.by_qualname: dict[str, str] = {}
        self.by_path: dict[str, str] = {}
        self.by_name: dict[str, set[str]] = defaultdict(set)
        self.by_suffix: dict[str, set[str]] = defaultdict(set)
        for node in code_nodes:
            if isinstance(node, ModuleNode):
                self.by_qualname[node.qualname] = node.id
                self.by_path[node.path] = node.id
            elif isinstance(node, ClassNode | FunctionNode):
                self.by_qualname[node.qualname] = node.id
                if not (isinstance(node, FunctionNode) and node.is_method):
                    self.by_name[node.name].add(node.id)
                parts = node.qualname.split(".")
                for start in range(1, len(parts) - 1):
                    self.by_suffix[".".join(parts[start:])].add(node.id)


def link_mentions(source: str, text: str, targets: MentionTargets) -> list[Edge]:
    """MENTIONS edges from the Doc `source` for everything `text` names, sorted by target."""
    best: dict[str, MentionMatch] = {}

    def found(target: str | None, match: MentionMatch) -> None:
        if target is not None and (target not in best or _RANK[match] < _RANK[best[target]]):
            best[target] = match

    for qualname in _QUALNAME.findall(text):
        found(targets.by_qualname.get(qualname), "qualname")
    for token in _PATH.findall(text):
        found(_path_target(token, targets), "path")
    for span in _CODE_SPAN.finditer(outside_fences(text)):
        found(_name_target(span.group(2), targets), "backtick_name")
    return [
        Edge(kind="MENTIONS", source=source, target=target, match=best[target])
        for target in sorted(best)
    ]


def _path_target(token: str, targets: MentionTargets) -> str | None:
    if "*" in token or "?" in token:
        return None
    path = token.removeprefix("./").rstrip(".").rstrip("/")
    if path.endswith(".py"):
        return targets.by_path.get(path)
    return targets.by_path.get(f"{path}/__init__.py")


def _name_target(span: str, targets: MentionTargets) -> str | None:
    name = span.strip().removesuffix("()")
    if not _NAME.fullmatch(name):
        return None
    if "." in name:
        candidates = targets.by_suffix.get(name, set())
    elif name in _COMMON_NAMES or (name.startswith("__") and name.endswith("__")):
        return None
    else:
        candidates = targets.by_name.get(name, set())
    return next(iter(candidates)) if len(candidates) == 1 else None
