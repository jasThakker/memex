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

**Numbers:** 0.5 h estimated.
