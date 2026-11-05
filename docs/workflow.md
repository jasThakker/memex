# Memex agentic engineering workflow

How Memex is built with Claude Code, and why each part of the workflow exists. The short rules live in CLAUDE.md; this file holds the reasoning. What actually happened in each phase is in DEVLOG.md.

## Setup

- Claude Code runs in the terminal inside VS Code. The user reviews every change in the VS Code editor before accepting it.
- One git branch per phase (`phase-N-<name>`), merged into `main` with `git merge --no-ff` when the phase is done. Each phase is one reviewable unit with a visible "Merge Phase N" commit in `git log --graph`, and `main` only ever holds finished phases. Phase branches are kept as markers.
- Docs are Markdown; HTML views in `docs/html/` are generated for reading in the browser.

## The loop for each phase

1. **Announce.** Claude explains in a few lines what the phase does and why, and waits for approval.
2. **Plan.** The user presses Shift+Tab into plan mode and says "Start Phase N". Claude reads DESIGN.md and the latest DEVLOG.md entry, then writes a phase plan listing its slices. The user edits and approves it.
3. **Slices.** For each slice:
   1. Claude adds or extends a fixture with the known answer and writes a failing test.
   2. The user reviews the diff in VS Code and accepts it.
   3. Claude runs `uv run pytest` and shows it failing (red).
   4. Claude implements; the lint hook reports any ruff problems, which Claude fixes in visible edits.
   5. Claude runs the tests passing (green).
   6. For slices touching ingest, graph, query or check_change, the user invokes the reviewer subagent with the exact prompt Claude provides, and decides which findings to fix.
   7. Claude proposes a commit message; the user approves; Claude commits.
4. **Close.** Claude drafts the DEVLOG.md entry and the user edits it. Claude names the next subagent to run (if any), why, and the exact prompt. The branch is merged into `main`.
5. **Reset.** The user runs `/clear`. Everything needed to continue is in CLAUDE.md (loaded automatically), DESIGN.md, DEVLOG.md, this file and git history.

## Why each element, and when it is not worth it

| Element | Decision | Why it helps here | When it is not worth it |
|---|---|---|---|
| Plan mode | Per phase, not per slice | Phases contain real design choices (resolution order, schema). Plan mode lets the user edit the plan before any file changes. | For single slices inside an approved phase it is ceremony: the phase plan already lists them. |
| Tests first on fixture repos | Keep: the strongest element | Graph extraction has objectively right answers. Small fixtures we write ourselves (`layered_app`, `plainrepo`) make those answers known, so tests are exact and fast. | Thin glue such as CLI argument parsing or FastMCP registration: one contract test covers it better than test-first. |
| Main session builds the core, one slice at a time, commit per green slice | Keep | Small slices keep diffs reviewable in VS Code and produce a clean commit history for the interview. | Never skipped. Claude proposes the commit message; the user approves. |
| Read-only reviewer subagent (`.claude/agents/reviewer.md`) | Keep, scoped to core logic | A fresh context that sees only DESIGN.md and the diff catches requirement gaps the authoring context rationalizes away. Restricted tools make "read-only" enforced, not promised. It checks correctness and requirement gaps only, not style. | Scaffolding, config and docs slices: little logic to get wrong. |
| Custom exploration subagent | Dropped: built-in Explore is enough | Mapping Mealie and drafting eval questions is a one-off, read-only task; Explore already has the right tools. Its findings come back to the main session, which writes `eval/questions.yaml` for the user to verify. | A custom agent would pay off only if the same exploration were repeated for many codebases. |
| Verifier subagent for the eval | Replaced by a headless harness (`eval/run.py`) | A subagent cannot cleanly restrict tool sets per condition or report token usage per run, and its runs are hard to reproduce. `claude -p --output-format json` with `--allowedTools` and `--strict-mcp-config` does both, and grading against set-valued answers is deterministic. | n/a. An LLM grader would bring back subjectivity, so questions are designed to have set-valued answers. |
| Parallel work in git worktrees | Keep, one split only | After the schema freeze (Phase 3), the docs layer (Phase 4) and the query tools (Phase 5) touch separate files. One worktree in a second VS Code window demonstrates the technique. | More than two streams: the user's review time is the bottleneck, not Claude's speed. The docs layer is small, so the time saved is modest. |
| Hook after edits (`.claude/hooks/lint.sh`) | Lint only, report only | Ruff problems in edited `.py` files are fed back to Claude immediately. The same hook regenerates the HTML view of edited `.md` files. | Auto-fixing would change files after the user reviewed the diff. Running tests after every edit fights test-first (tests are red on purpose) and gets slow once Neo4j tests exist, so tests run explicitly at each slice boundary instead. |
| Eval questions drafted early | Added | Writing the 12 questions in Phase 1, before tools exist, keeps them from being biased toward what Memex does well. Ground truth comes from exploration plus a manual check, never from Memex itself (that would be circular). | n/a |
| `/clear` between phases | Added | Long contexts lose accuracy, keep superseded ideas around (old names, dropped rules), and make every turn more expensive. Clearing also tests the docs: if Claude cannot continue from them alone, they are missing something. | Mid-phase, when unfinished work exists only in the conversation. Write it down first. |

## Subagents and when they run

Subagents are invoked deliberately by the user, never by automatic delegation. Claude gives the exact prompt at the right moment.

| Agent | Type | When |
|---|---|---|
| `reviewer` | Custom, read-only | After core-logic slices and once at the end of each phase |
| Explore | Built-in | Phase 1: map Mealie and draft eval questions |

Invoke with `@agent-reviewer ...` or "Use the reviewer subagent to ...".
