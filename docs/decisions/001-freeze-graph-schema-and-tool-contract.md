# ADR-001: Freeze the graph schema and the tool contract

- Status: accepted; amended by ADR-003 (the USES edge kind) and ADR-004 (the `check_change` models removed)
- Date: 2026-11-05 (end of Phase 3)

## Context

From Phase 4 on, work splits into parallel streams: the docs layer (Phase 4, in a git worktree) writes Doc nodes and MENTIONS edges, while the query tools (Phase 5) read every node and edge kind and return results to agents. Both depend on two files: `memex/graph/model.py`, which defines what ingest produces and the store writes, and `memex/query/models.py`, which defines what every MCP tool returns. If either changed while both streams were running, they would drift apart, and agents would see results whose shape changes between versions.

## Decision

Both files are frozen as of this ADR. Changing either one needs a new ADR in `docs/decisions/`.

**Graph schema (`memex/graph/model.py`, DESIGN.md section 7):**
- Node types `CodebaseNode`, `ModuleNode`, `ClassNode`, `FunctionNode`, `ExternalNode`, `DocNode` with their current fields, stored under the labels `Codebase`, `Module`, `Class`, `Function`, `External`, `Doc`.
- Ids: `{codebase}:{qualname}` for code, `{codebase}:ext:{dotted}` for externals, `{codebase}:doc:{path}#{anchor}` for docs; the Codebase node's id is its name. Every node carries `codebase`.
- One `Edge` dataclass for the edge kinds `DEFINES`, `IMPORTS`, `CALLS`, `INHERITS`, `REFERENCES`, `MENTIONS`. Only the fields a kind uses are set; in Neo4j, unset fields are not stored and `ref_kind` is stored as `kind`.
- Confidence labels `exact`, `inferred` and `ambiguous` (the last reserved for the stretch tier).
- `CodebaseNode` carries `files`, `parse_errors` and `unresolved_calls`.
- `GraphBatch` and `IndexStats` as the hand-off from ingest to the store.

**Tool contract (`memex/query/models.py`, DESIGN.md section 10):**
- The field sets asserted in `tests/unit/test_query_models.py` (`CONTRACT`), and each model's field types, required fields and defaults as recorded in `tests/unit/contract_schema.json` (docstrings are not part of it), for every model: the shared `SymbolRef`, `Symbol`, `Citation`, `DocRef`, and the results of `list_codebases`, `find_symbol`, `callers`, `callees`, `impact_of`, `search_docs`, `check_change`, the stretch `module_summary`, and `CodebaseStats` for `memex stats`.
- All models are immutable and reject unknown fields. Every tool result carries `truncated`; `CodebaseStats`, which only the CLI returns, does not.
- A tool taking a `symbol` returns `symbol=None` with `candidates` when a short name is ambiguous, and both empty when nothing matches. `check_change` returns ambiguous short names in `ambiguous`, each with its candidates.

**Not frozen:** how ingest decides which edges exist (resolution rules, extractor behavior), store internals (batch size, query text), and the implementation of query functions. These can improve without an ADR, as long as the shapes above stay the same and DESIGN.md is updated.

## Consequences

- Phases 4 and 5 can run in parallel against fixed shapes. The contract tests fail on any change to a field's name, type, required-ness or default, which makes an accidental change visible. After an ADR-approved change, the snapshot is regenerated with `MEMEX_UPDATE_CONTRACT=1` and its diff reviewed.
- Adding a node type, an edge kind, a node property or a result field later costs an ADR. Two foreseeable cases are already inside the freeze: the `ambiguous` confidence label and `module_summary`.
- `ClassNode.tablename` is the only class property extractors may set (`CLASS_PROPERTIES`). A future extractor that needs another one needs an ADR.
