# Memex dev log

One entry per phase. Record what was delegated and to which agent, what went wrong, and what the human changed.

<!--
Template:

## Phase N: <name> (YYYY-MM-DD)
**Goal:**
**Delegated:**
| Agent | Prompt (short) | Outcome | Accepted? |
|---|---|---|---|
**What went wrong:**
**What I changed (human edits and overrides):**
**Decisions / ADRs:**
**Numbers:** tests, nodes/edges indexed, eval scores, tokens, hours
**Next:** branch for the next phase, its slices, open questions for its plan, which subagent to run (if any) and the exact prompt
-->

## Phase 0: Planning and workflow (2026-11-04)

**Goal:** Agree on the design, the coding rules and the agentic workflow before writing any code.

**Delegated:**
| Agent | Prompt (short) | Outcome | Accepted? |
|---|---|---|---|
| None | Planning stayed in the main session, in plan mode. Repo facts were checked read-only (Mealie tag and sha, folder layout, AGENTS.md, local uv and Python). | Planning proposal | Yes, after one round of changes |

**Proposal pushbacks on my starting workflow:**
- Custom exploration subagent: dropped in favor of built-in Explore (one-off, read-only task).
- Verifier subagent for the eval: replaced by a headless `claude -p` harness, which can isolate tool sets per condition and report token usage.
- Post-edit hook: lint only and report only. Auto-fix would change files after I reviewed the diff; running tests after every edit fights test-first.
- Plan mode: per phase, not per slice.
- Worktrees: one split only (docs vs tools).
- Added: draft eval questions in Phase 1 to avoid bias; `/clear` between phases.
- Python 3.14 instead of 3.12, because Mealie targets 3.14 and `ast` must understand its syntax.

**What I changed:**
- Made generality explicit: framework relationships behind an `Extractor` Protocol (SQLAlchemy first, Django sketched), default layer/domain behavior with no rules, and a `list_codebases` tool.
- Shrank the eval to 12 questions with one run per condition (configurable).
- Asked for hour estimates (~15 h total) and a must-have vs stretch cut line.
- Asked to confirm uv installs Python 3.14 (it does: 3.14.5 is downloadable and installs on first `uv sync`).

- Asked for an HTML version of every Markdown doc, for reading in the browser. Claude suggested generating it instead of hand-maintaining a copy (avoids drift and double diffs): `scripts/render_docs.py` (stdlib only, renders with marked + mermaid in the browser) writes gitignored `docs/html/`, and the hook regenerates on every `.md` edit. Accepted.

- Called out that the design and my explanations leaned too much on Mealie, when Memex is meant to be a general tool for any Python repo. Claude's audit: the core was already Mealie-free, but Mealie leaked in through the main fixture ("mimics Mealie"), domain options designed only from Mealie, a Mealie-named fetch script and smoke marker, a hardcoded Doc `kind` list, and having Mealie as the only real-repo evidence. Applied fixes: DESIGN.md leads with the general tool and lists Mealie under "Benchmark codebases"; fixture renamed `layered_app` and described by generic patterns; a guardrail test bans benchmark names from `memex/`; httpx 0.28.1 added as a second, differently shaped repo indexed with defaults only, with its own smoke tests; `fetch_codebases.py` reads repos from `memex.toml`; `doc_kinds` became config; smoke marker renamed `realrepo`.

**What went wrong:** Claude explained layers, domains and tool usage almost only through Mealie examples, which made the general design look Mealie-specific. Thinking through httpx also exposed a bug in the default labeling rule: mapping leading-underscore names to `shared` would have labeled nearly all of httpx (`_client.py`, `_models.py`, ...) as one domain. Fixed by dropping one leading underscore instead. One of my design choices: `module_summary` and the `ambiguous` call tier moved below the cut line to fit the time budget.

**Decisions / ADRs:** ADR-001 (schema freeze) planned for Phase 3, ADR-002 (no LLM in check_change) for Phase 6.

**Questions I asked along the way:** what GraphBatch is, what an ADR is, who operates the graph, what layers and domains are, what the fixture is, why `/clear` between phases, what a persistent Neo4j volume is. Answered in chat; not added to DESIGN.md.

**Handoff audit before `/clear`:** Claude checked the conversation against the docs and found things that existed only in chat: the workflow rationale table, the phase-start reading rule, the branch-per-phase convention and the Phase 1 slice list. Added `docs/workflow.md`, CLAUDE.md workflow lines and this entry's "Next" section. Claude also tried to add a glossary, an agent-usage walkthrough (with a Mealie example) and a Neo4j volume note to DESIGN.md; I rejected those: DESIGN.md stays a general design spec, not an explainer, and gets no benchmark-flavored additions.

**Layer and domain labels, revisited:** I asked whether layers and domains were Mealie-specific. Decision: keep them as designed. They come from folder names by default for any repo, and repo-specific rules exist only in `memex.toml`. Rejected alternatives: renaming them to neutral terms, making them opt-in, or removing them.

**Fresh-context handoff check (agentic technique):** I was worried that after `/clear` a fresh session would make mistakes in Phase 1. Instead of trusting it, we tested it: Claude launched the built-in Explore subagent (read-only, no edit tools, no knowledge of this conversation) to read only the repo files and answer five questions: what Memex is, default layer/domain rules, the Phase 1 slices and "done", the workflow rules, and any gaps or contradictions. It is a cheap simulation of the next session, done while doc fixes cost nothing.
- Result: questions 1 to 4 answered correctly, each with a file citation. Memex is general; Mealie and httpx are benchmarks; the default rules match, including the httpx example; all 6 slices and the done criteria match; the workflow rules match.
- It found 22 gaps. The real doc bugs: the guardrail as worded would ban the word "memex" inside `memex/`, because Memex is itself in the benchmark table; the reviewer phase-end rule contradicts "not worth it for scaffolding"; workflow.md claimed the reviewer is read-only by tool restriction, but it has Bash; the "all tests" command also selects `realrepo` tests; the phase-start reading list differs between CLAUDE.md and workflow.md; DESIGN.md status line is stale; the DEVLOG template has no "Next" section.
- The rest are details nobody had decided yet: pyproject layout, Docker image tag and auth, config path bases and defaults, fetch re-run behavior, the `questions.yaml` format, how the guardrail can fail first, `__init__.py` labeling. These are left for Phase 1 plan mode (Phase 2 for `__init__.py`).
- Applied fixes for all 7 doc bugs on `phase-0-handoff-fixes`. Declined two optional extras: indexing DEVLOG.md and workflow.md in the Memex self-index, and making the handoff check a standard step at the end of each phase.
- Limitation: the subagent may not see Claude's memory notes, which a real fresh session loads, so this check is slightly stricter than the real handoff.

**Numbers:** 0.5 h estimated. Handoff check: 1 subagent run, about 50k subagent tokens, 2.5 minutes.

**Next:**
- `phase-0-workflow` merged into `main` with --no-ff; Phase 1 starts by creating `phase-1-scaffold` from `main`.
- Phase 1 slices: (1) `pyproject.toml`, `.python-version` (3.14), empty `memex/` package, so the lint hook goes live; (2) `docker-compose.yml` with Neo4j 5, healthcheck, persistent volume; (3) `memex.toml` (mealie, httpx, memex) and `memex/config.py`, test-first; (4) guardrail test banning benchmark names in `memex/`; (5) `scripts/fetch_codebases.py` with commit check, `vendor/` gitignored; (6) Claude gives the exact Explore prompt to map Mealie and draft 12 eval questions, which the user verifies by hand before they go into `eval/questions.yaml`.
- Open questions to settle in the Phase 1 plan (from the handoff check): pyproject layout, build backend, `[project.scripts]`, ruff rules, whether `uv.lock` is committed, and which DESIGN.md dependencies go in now; pytest marker definitions and default `addopts`; `.gitignore` entries (`__pycache__/`, `.venv/`, `vendor/`); Neo4j image tag, auth, ports, volume name and how "healthy" is checked; `memex.toml` path bases (package-relative vs root-relative), defaults for optional keys, unknown-key handling, config types; fetch script clone depth, re-run behavior and entries without `source`; how the guardrail test is shown failing first; the `eval/questions.yaml` format; whether `.python-version` is `3.14` or `3.14.5`.
- No subagent to run before Phase 1. No reviewer at the end of Phase 1 (scaffolding only).

## Phase 1: Scaffold + exploration (2026-11-05)

**Goal:** Everything later phases depend on: project tooling, local Neo4j, the codebase registry, the guardrail, the fetch script for the benchmark repos, and the 12 eval questions, drafted before any Memex tools exist.

**Delegated:**
| Agent | Prompt (short) | Outcome | Accepted? |
|---|---|---|---|
| Explore (built-in, read-only) | Map the Mealie backend and contributor docs; draft 12 questions (3 locate, 3 callers, 2 layer_domain, 2 doc_rules, 2 check_change) with set-valued answers and file:line evidence; do not consider any particular tool | 12 questions in about 7 minutes, 39 tool calls, about 100k subagent tokens | Yes, after verification (below) |

**How the eval questions were verified (three layers):**
1. Claude, with a script: parsed Mealie with `ast` and confirmed all 69 expected items exist (52 symbols, 17 doc references).
2. Claude, by re-grepping: the five "list every X" answers (q01, q04, q05, q06, q07) are complete. For example, q04's 7 callers out of 27 `.create_one(` call sites.
3. Me, by hand: the judgment-heavy questions q02, q08, q10, q11, q12, using yes/no checks with links to each evidence line.

**What I changed:**
- Approved all 15 open-question defaults in the Phase 1 plan.
- q11: added the `code-contributions.md` rule "If you've changed APIs, update the documentation."
- q12: dropped `__registrar`, a module-level variable that Memex's graph cannot represent; `get_parser` stands in for it.
- Kept all 7 doc sections in q10.
- Did not run `/clear` before Phase 1; continued in the same session.

**What went wrong:**
- The first `uv sync` built the editable install before `memex/` existed, so the import test stayed red after the package was created. Fixed with `uv sync --reinstall-package memex`.
- Once ruff was installed, the hook found 3 lint problems in Phase 0's `scripts/render_docs.py`, and ruff treated `memex` as third-party until it was declared first-party in `pyproject.toml`. Both fixed in visible edits.
- The Docker daemon was not running for slice 2, and Claude's wait loop kept retrying instead of stopping at the first error, producing a wall of output.
- The hook also lints `.py` files outside the repo (a throwaway checker script in Claude's scratchpad). Harmless; not fixed yet.
- Claude miscounted the expected items at first ("40 symbols and 13 doc headings"; the real numbers were 53 and 16 before the q11 and q12 edits) and corrected it when asked.
- I found the hand-verification step confusing at first; Claude's instructions only became usable once they were concrete yes/no checks with one or two links per question.

**Side findings in Mealie** (useful for the demo): `RepositoryGeneric._query` calls `q.filter(...)` without using the result (`repository_generic.py:82`); the `generate_session` docstring points to a `with_session` function that does not exist; the ingredient-parser contributor doc is stale (it says "single method interface" and points to a missing `crfpp` folder).

**Decisions / ADRs:** Pydantic for config (frozen, unknown keys rejected); flat layout with hatchling; `uv.lock` committed; dependencies added only in the phase that uses them; doc references use the heading's plain text, with Markdown links reduced to their visible text.

**Numbers:** 6 slice commits; 30 tests passing in about 2 s; Mealie (53 MB) and httpx (9.3 MB) fetched in about 5 s; Neo4j healthy in about 10 s.

**Next:**
- Merge `phase-1-scaffold` into `main` with `--no-ff`; Phase 2 starts by creating `phase-2-parse` from `main`.
- Phase 2 (parse + classify, DESIGN.md section 15): the `layered_app` and `plainrepo` fixtures; `graph/model.py` (Node, Edge, GraphBatch); walker; parser (Module, Class, Function, DEFINES, IMPORTS, External); classifier with defaults and rules. Done means exact fixture tests, Mealie and httpx parse with 0 errors, and a layer/domain report for both that I sanity-check.
- Open questions for the Phase 2 plan: how `__init__.py` and `__version__.py` are labeled (dropping one underscore from `__init__` gives `_init__`); how relative imports resolve; the External id format; whether nested functions get their own nodes; whether `graph/model.py` is written now or only the parts Phase 2 needs.
- Carry to Phase 4: the doc chunker must store headings as plain text (links reduced to their visible text) so `path#Heading` references match.
- Possible post-v1 tool: "subclasses of X" (q01 showed `impact_of` mixes subclasses with other dependents).
- Reviewer: Phase 2 is the first phase with core logic. Claude gives the exact reviewer prompt after the first parser slice and once at the end of the phase.

## Phase 2: Parse + classify (2026-11-05)

**Goal:** Turn any Python codebase into Module, Class and Function nodes with DEFINES and IMPORTS edges, External nodes and layer/domain labels, with no database. Prove it on fixtures with known answers and on Mealie and httpx.

**Approved plan** (branch `phase-2-parse`, written before any code):

Decisions:
- `memex/graph/model.py`: one frozen dataclass per node label (`ModuleNode`, `ClassNode`, `FunctionNode`, `ExternalNode`, `DocNode`), `Node` is their union; one frozen `Edge(kind, source, target, line, confidence, names, position, ref_kind, attr, extractor, match)`; `GraphBatch(codebase, nodes, edges, stats)`. Written in full now because the schema freezes after Phase 3.
- External ids are `{codebase}:ext:{dotted}` with a `codebase` property (DESIGN section 7 updated).
- Each `packages` entry is a path relative to `root`; module names start at that directory's own name (`src/pkg` gives `pkg.*`).
- Classes and functions at module level or inside classes get nodes; anything defined inside a function does not (DESIGN section 13 updated).
- Imports: every import statement anywhere in the module. `from m import a, b` gives one IMPORTS edge per name: to `m.a` if it is a class, function or submodule in the codebase, else to module `m`, else to External `m.a`. Relative imports resolve against the importing module's package. Re-exports through a package `__init__` are followed up to 5 hops. `import *` gives one edge to the module with `names=("*",)`.
- `__init__.py` is labeled as its directory (`pkg/__init__.py` is layer `root`; `pkg/routes/__init__.py` is layer `routes`, no domain). Other dunder files lose both underscore pairs. Domain rule order: underscores, first matching prefix, first matching suffix, singularize (`-ies` to `-y`; drop trailing `-s` except after `s`, `u`, `i`; keep `-ics`). DESIGN section 8 updated.
- `layers` keys match as path prefixes under the package directory, longest first; unmatched folders use the default rule.
- Fixtures load through `tests/fixtures/memex.toml` (`layered_app` with rules, `plainrepo` with defaults).
- `GraphBatch.stats` carries file count, parse errors and layer/domain counts; the Phase 2 report is printed with a one-line command (the `memex stats` CLI is Phase 3).
- Reviewer runs twice: after slice 3 and at phase end. CLAUDE.md reworded to "after each group of core-logic slices named in the phase plan".

Slices:
1. Model + walker (`memex/graph/model.py`, `memex/ingest/code/walker.py`, both fixtures).
2. Parser (`memex/ingest/code/parser.py`: nodes, DEFINES, raw imports, parse errors).
3. Imports (`memex/ingest/code/resolver.py`: `link_imports`), then reviewer run 1.
4. Classifier (`memex/ingest/code/classify.py`).
5. Pipeline + real repos (`index_code` in `memex/ingest/code/__init__.py`, `-m realrepo` smoke tests for Mealie and httpx, layer/domain reports for the user), then reviewer run 2.

Slices as built: (1) model + walker + both fixtures, (2) parser, (3) imports, then reviewer run 1 and its fixes, (4) classifier, (5) `index_code` pipeline + `-m realrepo` smoke tests, then reviewer run 2 and its fixes. One commit per step.

**Delegated:**
| Agent | Prompt (short) | Outcome | Accepted? |
|---|---|---|---|
| reviewer (run 1) | Slices 1 to 3 against DESIGN sections 4, 5, 7, 12, 13 and this entry's decisions; focus on syntax cases, import edge cases, real-repo breakage, weak tests | 10 findings; about 52k subagent tokens, 2.7 minutes | 9 fixed in "Address reviewer run 1"; skipped: merged IMPORTS edges hide a plain `import m` next to `from m import A` (cosmetic) |
| reviewer (run 2) | End of phase: run 1 fixes, classifier, pipeline, smoke tests against sections 4, 5, 7, 8, 12, 13 | 8 findings; about 67k subagent tokens, 2.7 minutes | 7 fixed in "Address reviewer run 2"; deferred: star re-exports ignore `__all__` |

**What the reviewer caught that I and Claude had missed** (the case for a fresh-context reviewer): two nodes could get the same id (a `def utils()` in `pkg/__init__.py` next to `pkg/utils.py`, overlapping `packages` entries); `from .api import api` resolved to the submodule instead of the function; IMPORTS edges could point at nodes that were dropped as duplicates; a package could import itself; excluded internal modules became External nodes; `@overload` stubs hid the real implementation; several tests asserted too little to fail.

**What went wrong:**
- The `reviewer` agent was not available after `/clear`; the session had to be restarted (`claude --continue` kept the conversation) before it loaded.
- The tests written for run 1 exposed a parser bug of Claude's own: definitions in `try` blocks came out of source order (`finally` before `except`).
- One test (the deep-expression guard in the parser) was written after the code. Claude checked it by disabling the guard and watching the test fail.
- Splitting slice 5 from the run 2 fixes into two commits needed a stash; the pop conflicted on `test_index.py` and was resolved from a backup, verified against the stash. Each of the two commits passes its tests on its own.
- Early test files had long lines; the lint hook flagged them and they were fixed in visible edits.

**What I changed (human edits and overrides):**
- Approved DEFINES from Class to Class for nested classes (DESIGN section 7 updated).
- Approved import resolution beyond the plan's wording: re-exports through any module, through star imports, and merged edges per target.
- Approved that domain rules normalize every domain, not only those in mapped layers.
- Decided to document the `fixe` label instead of adding an `-es` singularize rule.
- Asked for reviewer fixes as separate commits, and for slice 5 and the run 2 fixes as two commits instead of one.
- Questions I asked along the way: what a walker is, what "red" and "green" mean, what an ADR is (and that it is a development record, not a tool feature), and whether the reviewer shares this session's context (it does not: it sees only its prompt and the repo, and returns only its report).

**Known limits and imperfect labels** (documented, not fixed):
- Mealie: `db/fixes/` gets domain `fixe` (singularize only drops `-s`; an `-es` rule would need its own exceptions such as `types`). The meal plan concept is split across `meal_plan` (schema), `meal` (repos, from `repository_meals.py`) and `meal_plan_rule`.
- `try: from ._fast import x / except ImportError: from ._pure import x` with both modules walked resolves to the last binding.
- Star re-exports ignore `__all__`.
- Files and folders whose names are not Python identifiers are not walked (they cannot be imported as modules).

**Decisions / ADRs:** No ADR yet; the schema is still open until the end of Phase 3. Added to `graph/model.py` during the phase: `CodebaseNode` (with a `codebase` property) and `IndexStats.dropped_duplicates`.

**Numbers:**
- 8 commits on `phase-2-parse` (7 slice or fix commits plus the plan); 115 unit tests in about 2 s; 10 real-repo smoke tests in about 1 s.
- Mealie: 415 modules, 709 classes, 1,721 functions, 345 externals; 2,430 DEFINES and 4,580 IMPORTS edges; 0 parse errors, 0 duplicates, 0 dangling edges.
- httpx (defaults only): 23 modules, 87 classes, 429 functions, 79 externals; 516 DEFINES and 314 IMPORTS edges; 0 parse errors.
- Memex self-index: 10 modules, 0 parse errors.
- Reviewer: 2 runs, about 119k subagent tokens in total.

**Next:**
- Merge `phase-2-parse` into `main` with `--no-ff`; Phase 3 starts by creating `phase-3-resolve` from `main`.
- Phase 3 (resolve + extract + store, DESIGN.md section 15): CALLS with confidence labels and INHERITS in the resolver; the `Extractor` Protocol and the `sqlalchemy` extractor; the Neo4j store; `memex index` and `memex stats`; ADR-001 to freeze the schema.
- Open questions for the Phase 3 plan: whether the resolver's `_Index` becomes the `SymbolTable` of DESIGN section 6; how call resolution uses `RawImport.alias` and `module_level`; where INHERITS Externals merge with import Externals; how `CodebaseNode`, `indexed_at` and `IndexStats` reach Neo4j; batch size for `UNWIND` writes; how `memex stats` prints the layer/domain report (the Phase 2 report came from a throwaway script, not from `memex/`); which slice groups get a reviewer run.
- Carry to Phase 3: the "no REFERENCES without an extractor" tests (plainrepo, httpx) are trivially true until the extractor stage exists; check they still guard it. Fill `IndexStats.unresolved_calls`. Add the remaining section 12 smoke assertions (REFERENCES into `RecipeModel`, `Client.get` calls `Client.request`).
- No subagent to run before Phase 3. The reviewer runs inside Phase 3 after the slice groups its plan names; Claude gives the exact prompt each time.

## Phase 3: Resolve + extract + store (2026-11-05)

**Goal:** Add the remaining code edges (CALLS with confidence labels, INHERITS, REFERENCES through the opt-in `sqlalchemy` extractor), write the graph to Neo4j, add `memex index` and `memex stats`, and freeze the graph schema and the tool contract (ADR-001) so Phases 4 and 5 can run in parallel.

**Approved plan** (branch `phase-3-resolve`, written before any code):

Decisions:
- The resolver's `_Index` becomes the public `SymbolTable` of DESIGN section 6, shared with extractors.
- INHERITS: bases resolved like names (local, imported through re-exports, `alias.Name`), subscripts use their value, builtins become External `builtins.X`, `object` and `metaclass=` skipped, Externals merged with import Externals by id.
- CALLS in the DESIGN section 9 order, only for call sites inside function bodies; `C.m()` and `C(...).m()` added to rule 3; constructors resolve to `__init__`; external and builtin calls are not counted as unresolved; one edge per caller and callee.
- `Extractor` gets a second method, `class_properties`, so the `sqlalchemy` extractor can set `ClassNode.tablename`.
- Store: one write transaction per re-index, `UNWIND` in chunks of 1000, nodes per label, edges per (type, endpoint labels).
- `CodebaseNode` gains `files` and `unresolved_calls`; `query/models.py` holds the whole tool contract now, `module_summary` included.
- Dependencies `neo4j` and `testcontainers[neo4j]`, approved in the plan.
- Reviewer twice: after slices 1 to 3, and at phase end.

Slices: (1) SymbolTable + INHERITS, (2) CALLS, (3) Extractor Protocol + `sqlalchemy`, then reviewer run 1, (4) tool contract models, (5) Neo4j store, (6) CLI + `codebase_stats` + real repos, (7) ADR-001, DESIGN updates, reviewer run 2, DEVLOG, merge. Built as planned, with one fix commit after each reviewer run.

**Delegated:**
| Agent | Prompt (short) | Outcome | Accepted? |
|---|---|---|---|
| reviewer (run 1) | Slices 1 to 3 against DESIGN sections 4, 6, 7, 9, 12, 13 and the plan; focus on name binding, method lookup, unresolved counting, INHERITS and REFERENCES false positives, weak tests | 8 findings plus 4 weak tests; about 89k subagent tokens, 4.9 minutes | Fixed 1 to 6 and 8 plus the weak tests in "Address reviewer run 1"; deferred finding 7 (five rare binding cases, now in DESIGN section 13) |
| reviewer (run 2) | End of phase: run 1 fixes, contract models, store, CLI, ADR-001 and DESIGN against sections 6, 7, 9, 10, 12, 13 | 14 findings; about 114k subagent tokens, 5.7 minutes | All 14 fixed in "Address reviewer run 2" |

**What the reviewer caught that Claude had missed:**
- Parameters of nested defs and lambdas were not local, so `def inner(callback): callback()` became an `exact` edge to an unrelated module function.
- `super()` fell through to the inferred rule (a self-loop edge) and, in run 2, still did so inside local classes.
- Names re-exported from outside through a codebase module (`pkg/db.py: from sqlalchemy.orm import relationship`) silently broke INHERITS and the extractor.
- `class Base(Base)` lost its base.
- String relationships could land on a pydantic class with the same name; the run 1 fix then dropped `@declared_attr` tablenames (a regression caught by run 2).
- The contract test froze field names only, not types; the "atomic" store test failed before the transaction began; `ChangeCheck` had no place for ambiguous names, which would have needed an ADR after the merge.
- The reviewer cannot run code by design (Bash limited to git and pytest), so Claude reproduced every high and medium finding before the decision; all reproduced.

**What went wrong:**
- The inferred tier first matched common method names: 66 of Mealie's 262 inferred edges were `add`, `pop`, `encode`, `clear` landing on whichever class defines that name. Found only when looking at the real repo after slice 2; fixed by never inferring builtin type method names.
- Claude wrote expected counts in `test_cli.py` by guessing and was about to take them from the code's own output; it rewrote the test to count independently from the batch and to use numbers read from the fixture tree (the guess for the `order` domain was 6; the fixture has 7).
- Two test files named `test_cli.py` (unit and integration) clashed, because the test folders have no `__init__.py`; the integration one became `test_cli_neo4j.py`.
- Claude blamed slow unit tests on fixture re-indexing; profiling showed the Phase 1 fetch-script tests (real git) take 1.6 of about 2.6 s.
- Edits made through scripts bypassed the hook, so the HTML views were regenerated by hand once.
- The lint hook reported errors between parallel edits of one file (already fixed by the next edit); noisy but harmless.

**What I changed (human edits and overrides):**
- Chose to never infer builtin type method names (rule 5), after seeing the false positives.
- Agreed to measure the call-graph gap (ambiguous `get_one` and friends) in the Phase 7 eval before adding the `ambiguous` tier or attribute typing.
- Deferred reviewer run 1 finding 7; accepted every other finding of both runs.
- Kept the real-git fetch tests in the default run and reworded the DESIGN section 12 timing instead of hiding them behind a marker.
- Questions I asked along the way: what confidence labels mean, why each slice runs red before green, what `UNWIND` and chunks are, why the reviewer cannot run code, how many slices were left, and whether the project is on track.

**Known limits** (documented in DESIGN section 13, not fixed):
- 572 Mealie call sites go to names that several functions share (`get_one` 149, `page_all` 53, `create` 49): `callers` of repository methods will under-report.
- Bases in class bodies, `self.Inner()`, `cls(...).m()`, a later outside import shadowing a local class, outside star re-exports.
- `ForeignKey` in module-level association tables (24 of Mealie's 112) gives no edge; those many-to-many links still appear as `relationship` edges.

**Decisions / ADRs:** ADR-001 (`docs/decisions/001-freeze-graph-schema-and-tool-contract.md`) freezes `graph/model.py` and `query/models.py`, including field types through `tests/unit/contract_schema.json`. DESIGN sections 6, 7, 9, 10, 11, 12 and 13 updated to the code as built.

**Numbers:**
- 10 commits on `phase-3-resolve` (7 slice or docs commits, 2 reviewer fix commits, this entry); about 1.5 hours of wall-clock time against an estimate of 3.25 hours.
- Tests: 187 unit in about 2.6 s, 13 Neo4j integration in about 15 s (container included), 12 real-repo smoke tests.
- Mealie: 3,195 nodes and 9,777 edges (IMPORTS 4,580, DEFINES 2,430, CALLS 1,805 of which 1,614 exact and 191 inferred, INHERITS 709, REFERENCES 253 of which 88 foreign_key and 165 relationship); 34 REFERENCES into `RecipeModel`; 3,143 unresolved call sites, about two thirds of them library calls (68%, measured before the reviewer fixes); indexed into Neo4j in 4.4 s.
- httpx (defaults only): 624 nodes, CALLS 353 (336 exact, 17 inferred), 0 REFERENCES, 534 unresolved; `Client.get` calls `Client.request` (exact).
- Memex self-index: 18 files, 0 parse errors.
- Reviewer: 2 runs, about 203k subagent tokens in total.

**Next:**
- Merge `phase-3-resolve` into `main` with `--no-ff`. Phase 4 (docs) runs in a git worktree on `phase-4-docs`, in parallel with Phase 5 (query + MCP) on `phase-5-tools`, both from `main`.
- Open questions for the Phase 4 plan: heading text stored as plain text with links reduced to their visible text (carried from Phase 1); anchor format for Doc ids; how the mention linker matches qualnames, paths and backtick names without false hits on common words; where `index_docs` joins the `memex index` pipeline (both streams touch `memex/ingest/` and `cli.py`, so agree on the seam before the worktree starts); ADRs ingested for the Memex self-index.
- Open questions for the Phase 5 plan: the `fastmcp` dependency; how tools get a driver and validate `codebase`; whether `list_codebases` reuses `codebase_stats`; the 4 KB size budget against real Mealie results; where short-name ambiguity is resolved.
- Carry: measure in the eval how often the shared-method-name gap costs an answer; the `ambiguous` tier and attribute typing wait for that data.
- No subagent to run before Phases 4 and 5. The reviewer runs inside each after the slice groups its plan names; Claude gives the exact prompt each time.

## Phase 4: Docs (2026-11-05)

**Goal:** Index each codebase's Markdown docs as Doc nodes (one per heading chunk) with MENTIONS edges to the code they name, so Phase 5's `search_docs` and Phase 6's `check_change` have rules to cite. Built in the git worktree `../memex-docs` on `phase-4-docs`, in parallel with Phase 5 on `phase-5-tools`.

**Approved plan** (written before any code):

Seam with Phase 5 (agreed before the worktree started): Phase 4 owns `memex/ingest/` and adds `index_codebase(codebase) -> GraphBatch`; in `memex/cli.py` it changes only the `index_code` call in `_index`; no changes to `memex/query/`, `memex/mcp/` or the frozen models; Phase 4 merges into `main` first.

Decisions (the open questions from Phase 3's "Next"):
- Heading text is plain text: links reduced to their visible text, code and emphasis markers dropped.
- Doc id anchor = the heading's plain text, ` (2)`, ` (3)` for repeats in one file, empty for text before the first heading. Ids then equal the eval's `path#Heading` references.
- Mentions without false hits on common words: whole qualnames, root-relative paths, and backticked names that are unique and not a dunder, keyword, builtin or builtin type method name; ambiguous names give no edge.
- ADRs in the self-index: `doc_kinds` labels `docs/decisions/*.md` as `adr`.
- No new dependencies: a line-based chunker, not a Markdown library.

Slices: (1) chunker, (2) loader and kinds, (3) mention linker, (4) `index_codebase` and the CLI line, then reviewer run 1, (5) Neo4j and real-repo tests plus the ADR kind, (6) DESIGN updates, reviewer run 2, DEVLOG, merge. Built as planned, with one fix commit after each reviewer run.

**Delegated:**
| Agent | Prompt (short) | Outcome | Accepted? |
|---|---|---|---|
| reviewer (run 1) | Slices 1 to 4 against DESIGN sections 4, 5, 7, 12 and the Phase 4 decisions; focus on misdetected headings, anchor collisions, mention false hits and misses, off-by-one line ranges, weak tests | 15 findings, none high; about 59k subagent tokens, 4.2 minutes | Fixed 1 to 6, 8, 10, 11 and the three test gaps in "Address reviewer run 1"; documented 7, 9 and part of 5 in DESIGN section 13 |
| reviewer (run 2) | End of phase: run 1 fixes, slice 5 tests, DESIGN updates and the whole docs layer against DESIGN sections 5, 7, 12, 13; regressions, Doc id collisions, real-doc mentions, the Phase 5 seam | 9 findings, 1 high; about 100k subagent tokens, 6.5 minutes | Fixed 1, 2, 4, 7, 8 in "Address reviewer run 2"; documented 3, 5, 6, 9 and its section 13 omissions |

**What the reviewer caught that Claude had missed:**
- Run 1: wrapped list items, lazy quote lines and HTML followed by `---` became setext headings; a ```` ```cmd``` ```` line opened a fence that swallowed the rest of the file; headings inside HTML comments were indexed; a 4-space line closed a fence; form feeds shifted every line number; a `../` docs glob was silently accepted.
- Run 1, tests: the common-name guard, the uniqueness check and the setext guards could each be deleted with every test still green. Claude's own mutation check then found the thematic-break guard was still uncovered and added a test for it.
- Run 2: the run 1 multi-line setext fix was a regression (a list interrupting a paragraph, then `---`, made the whole run one heading); absolute and empty docs globs crashed with a traceback; two run 1 fixes had no test that failed without them.
- Claude reproduced every behavior finding of both runs before the decision. All reproduced; none changed any chunk or mention in the three benchmarks' docs. In run 1, the `../` glob was silently accepted rather than crashing as the report said.

**What went wrong:**
- The first mention rule linked bare method names. Checked on real docs after slice 3, most were ordinary words (`slug`, `groups`, `json`, `timeout`, `auth`, `headers`); fixed by requiring `Class.method` for methods. Claude first said 9 such edges; the list it showed had 11.
- A slice 2 test used a glob with `*` as a `pytest.raises(match=...)` regex; Claude caught it before running and escaped it.
- Claude said slice 6 would add no new DESIGN sections, then added the subsection "Doc chunks and mentions" to section 7, and flagged it afterwards instead of asking first.
- The lint hook reported undefined names between parallel edits of one file (already fixed by the next edit), as in Phase 3.

**What I changed (human edits and overrides):**
- Chose the anchor format (plain text plus ` (2)`), the strict backtick-name rule and the `adr` kind for the self-index.
- Chose to never link bare method names, after seeing the false hits on real docs.
- Chose that the Codebase node's `parse_errors` counts doc files too, so the summary count matches the listed errors (the plan said code only).
- Accepted Claude's fix-or-document split for both reviewer runs, and kept the new DESIGN subsection.
- Questions I asked along the way: how many slices were left, what Claude recommended about running reviewer run 1 before slice 5, why Claude mentioned Phase 3 during Phase 4 (it was only the precedent for a separate reviewer-fix commit), and whether the next step was for me to paste the reviewer prompt.

**Known limits** (documented in DESIGN section 13, not fixed):
- `` `Depends(generate_session)` `` (Mealie AGENTS.md:34) does not link `generate_session`, a symbol eval q09 expects: names inside call spans are not linked.
- Backtick spans in HTML comments and indented code still link; headings in blockquotes and list items are not detected; a leading `---` rule is read as front matter.
- Anchors are reduced by pattern: `Optional[str]` gives `Optionalstr`, angle brackets outside code vanish, escapes and entities are kept.

**Decisions / ADRs:** No ADR: the graph model and tool contract are unchanged (Doc, MENTIONS and `doc_text` were already frozen by ADR-001). DESIGN sections 5, 7, 12 and 13 updated to the code as built.

**Numbers:**
- 9 commits on `phase-4-docs` (6 slice or docs commits, 2 reviewer fix commits, this entry); about 1.1 hours from the Phase 3 merge to the last fix commit, against an estimate of 1.5 hours.
- Tests: 280 unit in about 2.5 s, 17 Neo4j integration in about 18 s (container included), 17 real-repo smoke tests.
- Mealie: 247 Doc nodes (36 files: 1 agents, 9 contributor, 26 user), 23 MENTIONS (all 23 checked by hand: no false hits), 0 doc parse errors; indexed into Neo4j in 7.1 s. Full-text "manually edit" returns the generated-types rule (`AGENTS.md#Backend Architecture (mealie/)`) third, after `#Common Gotchas` and `#Frontend Architecture (frontend/)`.
- httpx (defaults only): 121 Doc nodes from 14 files, all kind `doc`, 36 MENTIONS.
- Memex self-index: 30 Doc nodes, 46 MENTIONS.
- All 11 doc references in `eval/questions.yaml` exist as Doc ids (now a realrepo test).
- Reviewer: 2 runs, about 159k subagent tokens in total.

**Next:**
- Merge `phase-4-docs` into `main` with `--no-ff` (keep the branch). Then the Phase 5 session merges `main` into `phase-5-tools`; reviewer run 2 found that the two branches merge with no conflicts.
- For Phase 5 (`search_docs`): Doc ids are `{codebase}:doc:{path}#{anchor}` with the anchor as the heading's plain text; ranking matters (the Mealie rule above ranks third for "manually edit"); `memex index` now writes docs, so re-index all three codebases after the merge.
- Carry to Phase 6 (`check_change`): guideline retrieval should not rely on MENTIONS alone, because names inside call spans (`Depends(generate_session)`) are not linked; measure in the Phase 7 eval whether that costs q09 before widening the mention rule.
- `vendor/` was fetched separately into the worktree for the realrepo tests; it can be deleted with the worktree.
- No subagent to run before Phase 6. The reviewer runs inside Phase 6 after the slice groups its plan names; Claude gives the exact prompt each time.

## Phase 5: Query + MCP (2026-11-05)

**Goal:** Build the read side agents use: `list_codebases`, `find_symbol`, `callers`, `callees`, `impact_of` and `search_docs` in `memex/query/`, a thin FastMCP server over them, `memex serve` and `.mcp.json`, so a Claude Code session can ask what depends on a symbol and get compact, cited structure instead of grepping. Built on `phase-5-tools` in the main checkout, in parallel with Phase 4 in the worktree `../memex-docs`.

**Approved plan** (written in plan mode before any code; `/Users/jasthakker/.claude/plans/start-phase-5-declarative-teacup.md`):

Decisions:
- `fastmcp` dependency; MCP tests use the in-memory client through `asyncio.run`, no `pytest-asyncio`.
- Query functions take `(driver, codebase, ...)`, hold all Cypher and the range checks (`limit` 1 to 200, depth 1 to 5) and raise `ValueError`.
- Scope check in `query/scope.py` (`UnknownCodebaseError` or the new `NotIndexedError`), run by the server before every tool except `list_codebases`.
- Symbol rule: exact qualname wins, else qualnames ending in the given dotted segments; several matches are candidates, never a guess.
- `find_symbol` ranks exact qualname, then suffix, then a case-insensitive substring of the last segment.
- `callers`/`callees`: breadth first, one query per level, shortest distance; a class stands for its own `__init__`.
- `impact_of`: start set is the symbol plus everything it DEFINES; reverse CALLS, INHERITS, REFERENCES, IMPORTS; modules are leaves; grouped by layer; `total` before truncation; up to 5 docs.
- `search_docs`: `doc_text` index, Lucene syntax escaped, snippets of at most 200 characters.
- Size budget: DESIGN's defaults (20/50/100/10) could not fit its own 4 KB budget (about 280 B per dependent), so the defaults were lowered to fit (my choice): find_symbol 10, callers/callees 12, impact_of 12 (8 after measuring Mealie), search_docs 5.
- `build_server(driver, registry)` with one wrapper per tool and no logic; `memex serve` on stdio.

Slices: (1) list_codebases + scope check, (2) resolve_symbol + find_symbol, (3) callers + callees, then reviewer run 1, (4) impact_of, (5) search_docs, (6) MCP server + `memex serve`, (7) merge `main` (Phase 4), real-repo tool tests, `.mcp.json`, README, DESIGN, reviewer run 2, live check. Built as planned, with one fix commit after each reviewer run.

**Delegated:**
| Agent | Prompt (short) | Outcome | Accepted? |
|---|---|---|---|
| reviewer (run 1) | Slices 1 to 3 against DESIGN sections 4 and 10 and plan decisions 2 to 6 and 9; focus on symbol edge cases, ranking and truncation, the BFS, the class-to-`__init__` rule, Cypher parameters, weak tests | 3 medium and 4 low findings plus 7 weak tests; about 46k subagent tokens, 2.3 minutes | Fixed 1, 2, 4, 5, 6 and all weak tests in "Address reviewer run 1"; documented 3 (DESIGN section 13 and the `callers` description); deferred 7 (timed in slice 7) |
| reviewer (run 2) | End of phase: run 1 fixes and slices 4 to 7 against DESIGN sections 4, 10 to 13 and plan decisions 7 to 11; Phase 4 code out of scope | 2 medium and 5 low findings plus 9 weak tests, none high; about 99k subagent tokens, 6.3 minutes | Fixed all 7 and 5 of the weak tests in "Address reviewer run 2"; left 4 weak tests with reasons (schema types already frozen by `contract_schema.json`, writes guarded by READ routing, fixture too small for the budget, one shared scope wrapper) |

**What the reviewer caught that Claude had missed:**
- Run 1: `resolve_symbol` returned every candidate with no cap: `__init__` alone gave 140 candidates in Mealie (about 21 KB) and `get_one` 31, far past the budget.
- Run 1: a recursive function never appeared as its own caller or callee (13 such edges in Mealie, 2 in httpx).
- Run 1: `list_codebases` listed indexed codebases that were no longer registered, which every other tool would reject.
- Run 1, tests: exact-versus-suffix, one short name of two kinds, `find_symbol` tier 0, truncation at a deeper level and at exactly the limit were all untested.
- Run 2: snippets matched substrings (`orm` landed in "Information" and missed the real word); a cut already on a space dropped a word that fitted.
- Run 2: impact docs listed every symbol a section mentions, not only related ones; DESIGN said docs on the symbol come first while the code ranked any start-set member first; a pasted page as a query could hit Lucene's clause cap as a raw Neo4j error; the impact step query had no label and could not use the id index.
- Claude reproduced the medium findings of both runs on the real repos (Mealie and httpx batches, or a direct snippet call) before the decision; all reproduced.

**What went wrong:**
- The first size test measured `json.dumps` with spaces, not the compact JSON text the agent receives (4,203 B against 3,900 B on the wire). Fixed to measure the wire text; the margin was still thin, which the Mealie measurement then confirmed.
- On Mealie, `impact_of` at limit 12 reached 4,878 B (`AllRepositories`); the default became 8 (worst seen 3,698 B), as the plan allowed.
- Claude twice inserted a new test between a `@pytest.mark.parametrize` decorator and its function, which broke test collection until it moved the decorator back.
- Two test expectations were wrong as first written: the doc cap made `impact_of` truncated at the default depth, and ordering docs by path alone would have dropped the doc on the symbol itself. Both caught before commit.
- The first word-drop snippet test passed on the buggy code (equal-width words never put a cut on a space); rewritten as a property over several word widths, which then failed red.
- The slice 6 commit failed once: `git add` named the old path of the conftest rename, which was already staged.
- The resumed session could not use the `memex` tools after the restart (the server was connected, the tools never reached this conversation), so the live check ran in a fresh session. That is the fairer test anyway: it knew nothing about how the tools were built.
- Edits made through scripts bypassed the hook, so Claude ran ruff and regenerated the HTML views by hand, as in Phase 3.

**What I changed (human edits and overrides):**
- Chose to keep the 4 KB budget and lower the default limits rather than raise the budget.
- Approved the `tests/conftest.py` move, the doc ranking rule (docs on the symbol first) and one `truncated` flag covering dependents and docs.
- Accepted Claude's fix, document or defer split for both reviewer runs.
- Ran the live check myself in a fresh session: "In mealie, what depends on RecipeModel?" and "In httpx, what calls Client.request?" Both were answered through the tools; the second also found a missing caller by grepping (see below).
- Questions I asked along the way: whether plan mode had already been done for both phases, how my approval could start Phase 5 and still run Phase 4 in parallel, what Claude needed from me, whether the tests were failing on purpose (red before the code exists), how many slices there were, how the files under review get into the test container (they do not: only graph data goes into it), how many commits the project has, whether Phases 6 and 7 can run in parallel, what Phase 6 is about, and whether I could close the Phase 4 window.

**Known limits** (documented in DESIGN section 13, not fixed):
- Local names are not typed: httpx's module-level `request()` (`with Client(...) as client: client.request()`) is not a caller of `Client.request`, so `httpx.get()` and friends are missing from its callers. Found in the live check.
- `callers` of a class that only inherits `__init__` is empty (calls are stored on the base's `__init__`).
- Symbol lookup filters on qualname suffixes without an index; under 400 ms per tool call on Mealie, MCP round trip included.
- The 4 KB budget is measured, not bounded: `callers` of `AllRepositories.__init__` is 3,955 B at its default, and a repo with longer qualnames could exceed it.

**Decisions / ADRs:** No ADR: `graph/model.py` and `query/models.py` are unchanged. Default limits differ from the Phase 0 DESIGN (find_symbol 10, callers/callees 12, impact_of 8, search_docs 5); DESIGN sections 10, 11, 12 and 13 updated to the code as built, and the CLAUDE.md test commands split `-m "neo4j and not realrepo"` from the real-repo tests.

**Numbers:**
- 11 commits on `phase-5-tools` (7 slice commits, 2 reviewer fix commits, the merge of `main` with Phase 4, this entry); 55 commits on the branch in total.
- Tests: 300 unit in about 3 s; 162 Neo4j in about 31 s (container included), of which 21 are real-repo tool tests; 17 real-repo batch smoke tests.
- Dev database after the merge: Mealie 415 files, 3,195 code nodes plus 247 Docs, CALLS 1,805, REFERENCES 253, MENTIONS 23, indexed in 3.4 s; httpx 23 files, 121 Docs, CALLS 353, MENTIONS 36, 0 REFERENCES, 0.5 s.
- Sizes on Mealie at default limits (wire JSON): list_codebases 468 B, find_symbol 2,383 B, callers 2,569 to 3,955 B, callees 637 B, impact_of up to 3,698 B, search_docs 2,234 B.
- `impact_of RecipeModel`: 127 dependents within depth 3, the extractor's REFERENCES among them, all in `db_models`.
- Reviewer: 2 runs, about 145k subagent tokens in total.

**Next:**
- Merge `phase-5-tools` into `main` with `--no-ff` (keep the branch). Optionally remove the Phase 4 worktree with `git worktree remove ../memex-docs` (the branch stays).
- Phase 6 (check_change, DESIGN section 10 and 15) on `phase-6-check-change` from `main`, then Phase 7. Claude recommends running them one after the other: the eval has 2 check_change questions, and the workflow allows only the one worktree split.
- Open questions for the Phase 6 plan: how identifiers are pulled from a description without matching common words (reuse `resolve_symbol` and its candidates for `AmbiguousName`); how a Doc section is split into sentences for `quote`; negation in the modal-verb rules ("you don't need to avoid"); combining MENTIONS with full-text search, since names inside call spans are not linked (q09); whether `affected` reuses the `impact_of` walk through a shared helper; the size budget for `ChangeCheck`; ADR-002.
- Carry to Phase 7: measure in the eval how often the call-graph gaps cost an answer (shared method names, untyped locals like httpx `request()`) before adding the `ambiguous` tier or local typing.
- No subagent to run before Phase 6. The reviewer runs inside Phase 6 after the slice groups its plan names; Claude gives the exact prompt each time.

## Phase 6: check_change (2026-11-05)

**Goal:** Build `check_change(codebase, proposal)`: before making a change, an agent learns which code it affects and which documented rules apply, each quoted as one sentence with a stance and a citation to its own lines. No LLM in the server (ADR-002). Built on `phase-6-check-change` from `main`.

**Approved plan** (written in plan mode before any code; `/Users/jasthakker/.claude/plans/start-phase-6-lucky-piglet.md`):

Decisions (the open questions from Phase 5's "Next"):
- Names from a description: only code-shaped tokens (backtick spans, dotted, `snake_case`, `CamelCase`), resolved with the existing `resolve_symbol`; several matches become `AmbiguousName`, never a guess.
- `affected` reuses the `impact_of` walk through shared `start_set` and `walk` helpers, with no change in `impact_of`'s behavior.
- Two guideline sources: doc sections that MENTION the walked code, and a full-text search on the description (which also covers names inside call spans, which are not linked).
- Sentences come from a small splitter in a new pure module, `memex/query/rules.py`; a citation is the sentence's own line range, not the whole section.
- Stance from modal verbs, a negated requirement first ("you don't need to" gives `related`), then forbids, then encourages.
- Keep the 4 KB budget and lower caps where needed, as in Phase 5. The frozen contract models are unchanged.

Slices: (1) rules (tokens, sentences, stance), (2) resolution and `affected`, (3) mention guidelines, (4) search guidelines and merging, then reviewer run 1, (5) the MCP tool, (6) Mealie and httpx proposals, ADR-002, DESIGN and README, then reviewer run 2. Built as planned, with one fix commit after each reviewer run.

**Delegated:**
| Agent | Prompt (short) | Outcome | Accepted? |
|---|---|---|---|
| reviewer (run 1) | Slices 1 to 4 against DESIGN sections 4, 7, 9, 10, 13 and plan decisions 2 to 9; focus on sentence lines, stance, tokens, guideline selection and ranking, the impact refactor, the size budget, weak tests | 3 high, 8 medium and 5 low findings plus weak tests; about 74k subagent tokens, 4.7 minutes | Fixed all but 9 (size, deferred to slice 5 and 6 as planned) and parts of 10 and 16, in "Address reviewer run 1"; documented 14, the rest of 10 and 16, and the fence-only mention fallback in DESIGN section 13 |
| reviewer (run 2) | End of phase: run 1 fixes and slices 5 and 6 against DESIGN sections 4, 10 to 13, ADR-002 and plan decisions 2 to 10; the shared candidate cap, the MCP wrapper, the size budget on Mealie, the guardrail | 3 high, 7 medium and 5 low findings, run 1 fixes confirmed with no regressions; about 91k subagent tokens, 5.1 minutes | Fixed all but the list-indented fence part of 8 and 13, in "Address reviewer run 2"; documented those two in DESIGN section 13 |

**What the reviewer caught that Claude had missed:**
- Run 1: two sentences on one line shared a dedup key, so the second was silently dropped; `must **not**` read as `encourages`; rules about a changed symbol's own module or folder were never found by mention, although DESIGN promised layers; the 2-per-section cap held per source, not per section; a short name used as an English word (`create`) counted as naming a symbol.
- Run 1, also: sentences after `**Never**`, pipe-less tables, file names and acronym plurals as tokens, names inside call spans in the description.
- Run 1, tests: synthetic doc line ranges used the same formula the code inverts, so they could not fail; the dedup test passed even if search found nothing; `in` checks hid extra sentences.
- Run 2: the file-name filter skipped backtick spans; explicit symbols had no length limit (one of 5,000 characters gave a 5,145 B result); DESIGN said "sentences with a stance come first" while the 6-guideline cut kept section order, so a `forbids` could be pushed out by `related` noise; an ambiguous name could keep exactly one candidate, which reads as a resolution; 10 resolved explicit symbols on Mealie came to 4,131 B.
- Run 2, also: sentences ending inside emphasis or quotes, fences inside blockquotes, an enclosing package that also imports the symbol ranked as a dependent, a method change missed rules on its class, and a real-repo test that passed for the wrong reason.
- Claude reproduced the high and medium findings of both runs (pure functions directly, sizes on the dev database) before the decision; all reproduced. Run 2's reviewer could not run scripts, so its sizes were estimates; Claude measured them.

**What went wrong:**
- Slice 1 dropped the plan's "a sentence may start with a code span" while handling `e.g.`; the slice 3 integration test exposed it, and a unit test was added and shown red first.
- In the run 1 fixes, the heading-only quote test passed before the fix (its text split into short sentences); Claude made it one long sentence and saw it fail. Claude also changed an expected `truncated` to `True` that the fix then showed was wrong, and put it back.
- The new table mode first read a list item after a table as a table row; the existing fixture caught it.
- The plan's size check came late: slice 6 measured 9.9 KB on Mealie for ten shared short names, far over budget. I chose a shared candidate cap; reviewer run 2 then found two more inputs over budget.
- Small slips caught before review: test constants defined below the `parametrize` that used them, a stray `if False` in an expected list, and an unneeded rename of test ids, reverted.
- Edits made through scripts bypassed the hook, so Claude ran ruff and regenerated the HTML views by hand, as in earlier phases.
- A usage limit paused the session between finishing slice 6 and its commit; work resumed from the conversation without loss.

**What I changed (human edits and overrides):**
- Approved the plan, including sentence-level citations and the pure `rules.py` module.
- Chose the shared candidate cap (3 per name, 8 in total, names past it listed with no candidates) over fewer names or documenting the overflow.
- Accepted Claude's fix, document or defer split for both reviewer runs, including counting enclosing classes in run 2, one level beyond the run 1 wording.
- Questions I asked along the way: how many slices the phase has (asked twice), whether I should just paste the reviewer run 2 prompt, whether only one phase is left after this one (Phase 7 is the last required one; 8 and 9 are optional), and to pick up after the usage limit reset.

**Known limits** (documented in DESIGN section 13, not fixed):
- Stance comes from modal verbs only: a rule phrased without one is `related`, and a sentence with both a requirement and a prohibition is `forbids`.
- Search matching counts any shared word of four letters or more outside a short stopword list, so generic words pick sentences: "a new service" on Mealie also quotes the security doc's "Denial of Service" sentences.
- HTML comments, indented code and fences indented four spaces or more in a list item are read as prose; a call span in a doc sentence (`Depends(get_session)`) does not name its argument; brand names in a description become unresolved tokens.
- The 4 KB budget is measured, not bounded: the largest Mealie case is 3,949 B.

**Decisions / ADRs:** ADR-002, check_change without an LLM. `graph/model.py` and `query/models.py` are unchanged, so no ADR-001 change. DESIGN sections 10 to 13 and the README updated to the code as built.

**Numbers:**
- 9 commits on `phase-6-check-change` (6 slice commits, 2 reviewer fix commits, this entry); about 1.4 hours of work from the Phase 5 merge to the last fix commit, not counting the usage-limit pause, against an estimate of 1.5 hours.
- Tests: 343 unit in about 3 s; 186 Neo4j in about 30 s (container included); 33 real-repo tool tests and 17 real-repo batch smoke tests.
- check_change on Mealie, wire JSON at default caps: 1,099 B (`RecipeModel`), 1,579 B (AppSettings proposal), 2,125 B (locales), 2,085 B (pip), 2,291 B (`AllRepositories`), 3,669 B (ten explicit symbols), 3,865 B (eight shared short names), 3,949 B (seven shared names and `AppSettings`).
- The three hand-written Mealie proposals each cite the expected AGENTS.md line: 121 (`forbids`, by mention), 144 (`forbids`, by search), 100 (`encourages`, by search).
- Reviewer: 2 runs, about 165k subagent tokens in total.

**Next:**
- Optional before the merge: a live check in a fresh Claude Code session (re-index Mealie first with `uv run memex index mealie`), for example "In mealie, I want to instantiate AppSettings directly in a new service. Is that allowed?", and confirm the citation points at the quoted line.
- Merge `phase-6-check-change` into `main` with `--no-ff` (keep the branch).
- Phase 7 (evaluation, DESIGN sections 14 and 15) on `phase-7-eval` from `main`: `eval/run.py`, `eval/grade.py`, the 12 questions in two conditions.
- Carry to Phase 7: measure whether q11 and q12 (check_change) are answered from the cited guidelines; whether generic-word search noise costs answers; whether the call-graph gaps from Phase 5 and the call-span gap (q09) cost answers, before widening any rule.
- No subagent to run before Phase 7. The reviewer runs inside Phase 7 after the slice groups its plan names; Claude gives the exact prompt each time.

## Phase 7: Evaluation (2026-11-05)

**Goal:** Measure Memex against plain file search on Mealie: the 12 questions from Phase 1, each asked in condition A (`Read`, `Grep`, `Glob`) and condition B (the Memex tools plus `Read`), with the same model, prompt and working directory. Grading is deterministic, the raw transcripts are committed, and the losses are reported. Built on `phase-7-eval` from `main`.

**Approved plan** (written in plan mode before any code; `/Users/jasthakker/.claude/plans/start-phase-7-abstract-coral.md`):

Decisions:
- `claude-sonnet-5-5`, N=1, pinned in `eval/config.toml`. You chose Sonnet over Opus and Haiku.
- Neither Mealie's CLAUDE.md (a copy of AGENTS.md) nor Memex's own CLAUDE.md is pre-loaded, so the doc questions measure retrieval. Your choice. Both conditions run from an empty folder outside the repo, with the codebase added through `--add-dir`.
- Transcripts are saved as stream-json, not json, so each `init` event (the tools actually offered) and every tool call are kept.
- One prompt for both conditions. It ends with a fenced json answer block and never names Memex.
- The grader is a deterministic set comparison with no LLM judge. Answers are normalized, then scored by precision, recall and F1 over the combined set of symbols and docs.
- One baseline call per condition measures B's fixed cost.

Slices:
1. The grader.
2. The runner, followed by reviewer run 1.
3. A smoke run: the two baselines, then q11 in condition B. This is the agreement from the end of Phase 6, and it replaces the live check skipped there.
4. The full run.
5. This write-up.

Built as planned, with one fix commit after the reviewer. Stream parsing moved from slice 2 into the grader, which reads the transcripts.

**Delegated:**
| Agent | Prompt (short) | Outcome | Accepted? |
|---|---|---|---|
| reviewer (run 1) | Slices 1 and 2 against DESIGN section 14 and plan decisions 1 to 7. Focus on grading fairness, isolation between conditions, prompt leaks, token accounting, determinism, failure handling and weak tests. No paid calls | 2 high, 6 medium and 6 low findings, plus weak tests; about 69k subagent tokens, 4.3 minutes | Fixed all 14 in "Address reviewer run 1"; finding 12 (the wording on fixed cost) was fixed in the report and DESIGN section 14 |

**What the reviewer caught that Claude had missed:**
- A cut-off transcript line (a timeout mid-write) crashed both the runner and the grader.
- Nothing checked, per run, that B really had the Memex server connected. A failed server would have been graded as condition B.
- The prompt named Memex through the root path (`.../memex/vendor/mealie`). Claude then found that the workdir name did too.
- A failed call counted as zero tokens and $0, so the condition that fails more would look cheaper.
- Doc headings were normalized unfairly to A: A reads raw Markdown, where q11's expected heading is a link.
- The calling session's environment was passed through unchanged. When Claude checked, it was worse than reported: `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_MESSAGING_SOCKET` and `CLAUDE_EFFORT` were all set. Each eval call would have inherited this session's identity, messaging socket and effort level.
- Resuming skipped failed transcripts; `meta.json` never recorded later invocations.
- Weak tests: the "never names Memex" test used a fake root, and the leak test checked only a fragment of each heading.
- Claude reproduced findings 1, 3, 5, 7 and 9 before the fix; the rest follow directly from the code.

**What went wrong:**
- Claude ran the reviewer-fix tests red before you had reviewed them, skipping that step of the slice loop. You reviewed tests and code together before the commit.
- The first `--questions` test showed red only because the option was missing; the folder-level grading code had been written before its test.
- Edits made through scripts bypassed the hook, so Claude ran ruff and regenerated the HTML views by hand, as in earlier phases.
- q07's expected answer is at module level, while both conditions answered with the functions inside those modules. Both found all six modules and both scored 0.00. The grading was left as committed rather than changed after seeing the results.

**What I changed (human edits and overrides):**
- Approved the plan, chose Sonnet 5.5 and chose to keep AGENTS.md out of the context.
- Approved fixing all 14 reviewer findings, with effort pinned to `high`.
- Approved the smoke run's cost before the full run.
- Pushed back on reading the result as "Memex is a demo of engineering discipline only". Graph-native questions (transitive impact, foreign keys, doc-to-code links, later several linked repos) are what grep cannot answer in one step, and this eval did not measure them. That framing is in the "Results" section below and in "Next".
- Questions I asked along the way: how many slices are left, how long the last two would take, whether Memex answered fewer questions, took longer or cost more, and whether we have a product to demo.

**Results** (`eval/results/full/results.md`; N=1, so no variance estimate):

| Condition | P | R | F1 | Input tokens (all) | Output | Turns | Cost | Time |
|---|---|---|---|---|---|---|---|---|
| A: Read, Grep, Glob | 0.64 | 0.79 | 0.68 | 501,869 | 23,036 | 80 | $0.71 | 177 s |
| B: Memex plus Read | 0.54 | 0.76 | 0.60 | 701,473 | 21,151 | 97 | $0.80 | 180 s |

- **Per question:** A won 5 on F1 (q02, q03, q09, q10, q11), B won 3 (q01, q04, q08), and 4 tied (q05, q06, q07, q12). Recall was 1.0 on 6 questions for A and 5 for B. F1 was 1.0 on 3 for A and 2 for B.
- **F1 by category, A vs B:** callers 0.96 vs 0.98; locate 0.70 vs 0.59; doc_rules 0.92 vs 0.57; check_change 0.59 vs 0.55; layer_domain 0.08 vs 0.11 (q07, see above).
- **Overall:** B found about as much as A (recall 0.76 vs 0.79), with more extra items, in the same time, for 13% more cost (40% more input tokens, mostly cache reads). Every run was valid and none errored.
- **Fixed cost:** B's prompt is 465 input tokens larger per request (5,983 vs 5,518 in the baselines).

**Why B lost, from the transcripts:**
- **Doc questions:**
  - On q09, `search_docs` ranked `AGENTS.md#Backend Architecture (mealie/)` first, yet the agent cited a heading that does not exist (`Database & Sessions`).
  - On q10, the top four hits were all correct, so the agent stopped and read lines 140 to 225 only. A grepped for "generated" and read most of AGENTS.md. Good ranking made B read less.
- **q04, the token outlier:** 160k input tokens for B against 32k for A.
  - `callers` on `RecipeService.create_one` returned 3 of the 7 callers. The four through `self.service` and `self.recipe_service` are the known v1 limit (DESIGN section 13).
  - The agent noticed the gap and read a 27k-character file to close it. It scored 1.00, so the gap cost tokens, not accuracy.
- **q11:** `base_url` is a field, and the graph has no field nodes. check_change resolved nothing (`affected.total = 0`), and all six guidelines it returned were search noise from the user docs: `ai-providers.md` and an OIDC sentence, picked by "provider" and "must". The agent recovered with `find_symbol` and `Read`. Its recall equalled A's (0.73), its precision was lower.
- **Precision in general:** both conditions listed extras that are arguably right but not in the expected sets, such as the `AIProviderCreate` subclasses that inherit `base_url`. B listed more.

**Where B was ahead:** callers (q04 the only perfect answer, q05 and q06 tied), q08 recall (0.60 vs 0.40, from following the graph to the scoping code), and fewer input tokens on 5 of 12 questions (q01, q05, q07, q10, q12).

**Carried from Phase 6, answered:**
- **Were q11 and q12 answered from check_change's cited guidelines?** No. On q11 they were noise; on q12 the answer came from `find_symbol`, `impact_of` and reading.
- **Does generic-word search noise cost answers?** Yes: on q11 it cost precision, and the expected doc sections were not among the guidelines.
- **Do the call-graph gaps cost answers?** On q04 they cost tokens, not accuracy.
- **Does the call-span gap cost answers on q09?** No: q09's miss was a hallucinated heading.

**Reading the result:** the 12 questions were written in Phase 1, before the tools, so they would not favour Memex. Most are one-hop, and most name their symbol outright, which is where grep is cheap on a repo of 415 files. Questions where a graph should matter were not tested: multi-hop impact ("what breaks if I change X"), relationships that are not textual calls (foreign keys, inheritance, doc mentions), and links across repos. Expecting Memex to win there is reasonable, but it is not a result yet. Its edges have known gaps, and a transitive walk compounds them.

**Decisions / ADRs:** none. `graph/model.py` and `query/models.py` are unchanged. DESIGN section 14 and the README were updated to the eval as built.

**Numbers:**
- 5 commits on `phase-7-eval`: 2 slice commits, 1 reviewer fix commit, the results, and the write-up with this entry. About 1.2 hours from the Phase 6 merge to this entry, against an estimate of 1.5 hours.
- Tests: 430 unit in about 3 s; 186 Neo4j in about 30 s (container included).
- Mealie re-indexed in 2.9 s: 3,442 nodes (Function 1,721, Class 709, Module 415, External 350, Doc 247) and 9,800 edges.
- Eval spend:
  - smoke run, 3 calls: $0.23;
  - full run, 26 calls: $1.53 (A $0.71, B $0.80, baselines $0.02);
  - reviewer: about 69k subagent tokens.

**Next:**
- Merge `phase-7-eval` into `main` with `--no-ff` (keep the branch). Phase 7 is the last required phase.
- Phase 8 (optional, polish): a README walkthrough and a demo script built on what works today:
  - `impact_of RecipeModel` (foreign keys across layers);
  - check_change on a proposal that names code, such as instantiating `AppSettings` (AGENTS.md:121, `forbids`);
  - httpx indexed with zero config;
  - the eval itself.

  Avoid field renames and `callers` through injected attributes in a live demo.
- Phase 9 candidates, in the order the data points to:
  1. Resolve calls through injected attributes typed in `__init__` (q04).
  2. Field nodes, so a field rename resolves (q11).
  3. Tell the agent when a result is complete or partial, so it stops re-checking.
  4. Tighten check_change's search matching (q11 noise).
  5. A small multi-hop impact eval (4 to 6 hand-verified "what breaks if I change X" questions) run in both conditions, with N=3. This tests the claim the current questions did not cover.
  6. Later: linking `External` nodes to another indexed codebase, for impact across repos.
- No subagent to run before Phase 8.

## Phase 9: Impact accuracy (2026-11-05)

**Goal:** Measure how accurate `impact_of` is on Mealie by hand before fixing anything or paying for an eval, then fix what the measurement shows. Phase 7 left the graph's case (multi-hop "what breaks if I change X") untested. Built on `phase-9-impact` from `main`. Phase 8 (polish) was skipped.

**Approved plan** (`/Users/jasthakker/.claude/plans/start-phase-9-begin-quiet-hickey.md`):
- Slice 1: a hand-verified check of four Mealie symbols, each testing a different edge path, with ground truth from grep and reading only, never from Memex.
- Then the fixes you chose from its results, test-first, a reviewer pass, a free re-run of the check, and a paid multi-hop eval only with your approval.

Built: slice 1 and three fixes. The reviewer ran after the fixes. The reviewer's findings were not fixed, the check was not re-run into the report, and the paid eval was not run: you chose to close the phase there, since Memex is for a demo.

**Slice 1, the check** (`eval/impact_check.md`): precision was 1.00 at depth 1 and on every CALLS chain. The problems were recall and one noise source:

| Symbol | What it tests | Recall before |
|---|---|---|
| `hash_password` | plain calls, depth 3 | 17 of 18 |
| `get_current_user` | `Depends(...)` | 5 of 10 |
| `RecipeService.create_one` | calls through `self.service` | 6 of 22 (depth 2) |
| `Tool` (ORM model) | relationships, use as a value | 13 of 25 |

At depth 2, `Tool` listed 74 more dependents, none correct: the walk kept going from classes reached by REFERENCES.

**Fixes** (each test-first: you reviewed the tests, then red, then green):
1. **Leaf rule** (`136a516`): a class reached by REFERENCES is not expanded, like a module. `Tool` went from 13 / 87 / 125 dependents at depths 1 / 2 / 3 to 13 at every depth.
2. **Typed attributes** (`e8fa0f0`): `self.a.m()` and `self.a.b.m()` resolve `exact` when the class types `a` through a property or cached_property's return annotation, or `__init__` assignments (`self.a: C`, `self.a = C(...)`, `self.a = p` with `p: C`). `create_one` went from 3 to 7 of 7 direct callers, and from 6 to 21 of 22 at depth 2.
3. **USES edges** (`92092c6`, ADR-003): a codebase function or class named as a value (`Depends(f)`, `select(Model)`, construction of a class with no `__init__`), from function bodies, their own defaults and class-body values. A pair REFERENCES already links is not repeated. `get_current_user` went from 5 to 10 of 10 direct dependents, `Tool` from 13 to 23 of 25. You approved three additions to the design: construction without `__init__` counts, REFERENCES pairs are not repeated, and the longest resolvable part of a dotted name is the target.

Not fixed by design: calls and values through local variables (`forgot_password.reset_password`, `parse_recipe_url_bulk`), base-class type arguments, annotations.

**Delegated:**
| Agent | Prompt (short) | Outcome | Accepted? |
|---|---|---|---|
| reviewer (run 1) | The three fix commits against DESIGN sections 7, 9, 10, 13, ADR-003 and the check. Focus on false edges, USES walking the wrong AST parts, the leaf rule with USES, the attribute cache, weak tests. No paid calls | 1 high, 4 medium, 4 low, plus weak tests and four doc mismatches; 8 of 9 reproduced on real code, the ninth with a fake driver; about 99k subagent tokens, 6 minutes | Not fixed: listed below and in DESIGN section 13 |

**Open issues from the reviewer** (none affect the four checked symbols):
- High: `schedule(self.repo.get_one)` with `repo` a property gives USES of the property, not `Repo.get_one`.
- Medium: an attribute typed in `__init__` stays typed when another method assigns a different class; whether a node reached in the same step by REFERENCES and another edge is expanded depends on qualname order; class-body names resolve at module scope; a def inside `if` or `try` in a class body is read as class-body values.
- Low: a function-level import in `__init__` is ignored when typing; `for self.c in ...` does not untype; a classmethod's USES uses typed attributes while its calls do not; an `inferred` call suppresses the receiver's USES.
- Docs: assigning `Model.x` gives USES; `super().m` and `C(...).m` as values give nothing; `Annotated[X, Depends(f)]` gives nothing; a class-attribute dependency reaches controller classes, not their route methods (ADR-003 says "every route").
- Weak tests: no property case for USES, nothing for the cases above, and one assertion in `test_uses.py` that cannot fail.

**What went wrong:**
- I did not predict three test changes before running green: `plainrepo` gained a correct typed-attribute edge, `test_cli.py` counts the same edges, and one impact test hit the default `limit` of 8 after USES grew `User`'s dependents to 9.
- The first edit of fix 1 used a constant before defining it; the hook caught it.
- The reviewer found that the USES tests checked mostly the cases I had thought of: H1 is the motivating pattern of fix 3 with a property instead of a parameter.

**What I changed (human edits and overrides):**
- Approved the plan, chose fixes 1 to 3, approved the USES design and its three additions.
- Chose not to fix the reviewer's findings and to skip the re-run and the paid eval: Memex is a demo.
- Asked whether Memex now works well; the answer was "more accurate on these four symbols, with known gaps".

**Decisions / ADRs:** ADR-003 (USES). `graph/model.py` `EdgeKind` and `query/models.py` `ImpactEdge` gained `"USES"`; the contract snapshot was updated.

**Numbers:**
- 4 commits on `phase-9-impact` plus this entry; about 2.5 hours from the start of the phase to this entry.
- Tests: 438 unit, 186 Neo4j, 52 real-repo.
- Mealie re-indexed: 3,442 nodes, 11,712 edges (CALLS 1,934, USES 1,783), 2,993 unresolved calls.
- No paid eval calls; reviewer about 99k subagent tokens.

**Next:**
- Phase 8 (demo UI), on `phase-8-demo` from `main`: an interactive graph of the indexed codebase with a small chat that answers through `claude -p` and the Memex tools.
- Later, if wanted: the reviewer's open issues, the re-run of `eval/impact_check.md`, and the multi-hop eval.
