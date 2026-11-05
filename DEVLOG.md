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

## Phase 2: Parse + classify (in progress, started 2026-11-05)

**Approved plan** (branch `phase-2-parse`). If this session was cleared, continue from here.

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

Slice status: 0 (handoff), 1 (model + walker), 2 (parser) 3 (imports), 4 (classifier) and 5 (pipeline + real repos) done. Mealie: 415 files, 0 parse errors, 0 dropped duplicates; httpx: 23 files, same. Known imperfect labels in Mealie, documented rather than fixed (DESIGN section 8): `db/fixes/` gets domain `fixe` (singularize only drops `-s`; an `-es` rule would need its own exceptions such as `types`), and the meal plan concept is split across `meal_plan` (schema), `meal` (repos, from `repository_meals.py`) and `meal_plan_rule`. Reviewer run 2 done: 8 findings, all fixed except `__all__` being ignored by star re-exports (deferred; DESIGN is silent on `__all__`). Known limit: `try: from ._fast import x / except ImportError: from ._pure import x` with both modules walked resolves to the last binding. Carry to Phase 3: the "no REFERENCES without an extractor" tests (plainrepo, httpx) are trivially true until the extractor stage exists; check they still guard it. Domain rules normalize every domain, not only those in mapped layers. Reviewer run 1 done: 10 findings, all fixed except merged edges hiding a plain `import m` next to `from m import A` (cosmetic). Import resolution also follows re-exports through any module and through star imports, and merges names that reach the same target into one edge. DEFINES also covers Class -> Class (nested classes; DESIGN section 7 updated).
