# ADR-004: Remove check_change; the agent composes the basic tools

- Status: accepted
- Date: 2026-11-06 (Phase 10)
- Supersedes: the `check_change` tool described in ADR-002. ADR-002's principle, no LLM inside the server, still holds.

## Context

`check_change` (Phase 6, ADR-002) turned a proposed change into the affected code and up to six quoted rules. It did this with hand-written text rules: patterns for code-shaped names, sentence splitting, a stopword list and stance labels from modal verbs. The Phase 7 eval measured it on the two change questions:

- **q11:** it resolved nothing (`base_url` is a field, and the graph has no field nodes), and all six guidelines were search noise picked by generic words such as "provider" and "must".
- **q12:** the answer came from `find_symbol`, `impact_of` and reading the code, not from its guidelines.

So the agent was already composing the basic tools to answer, and the text rules were the part of the server that was hardest to explain and to keep right. The judgment belongs to the calling agent, which is an LLM with the user's context; ADR-002 already said so.

Options:

- **Keep `check_change` and tune its rules.** More heuristics, on the part the agent did not use.
- **Put an LLM inside the server** to read the proposal and orchestrate the other tools. That is a second LLM behind the first, and it brings back everything ADR-002 rejected: an API key, network access, answers that vary between runs, a cost per call, and no testing against known answers.
- **Remove the tool and teach the workflow** in the server instructions, so the calling agent composes `impact_of` and `search_docs` and judges.

## Decision

Remove `check_change`, its models (`ChangeProposal`, `ChangeCheck`, `Guideline`, `AmbiguousName`, `ImpactSummary`, `LayerCount`) and `memex/query/rules.py`. The server instructions gain one paragraph:

> Before a change: call impact_of on each symbol you will change, to see what depends on it and which doc sections mention it; call search_docs with a short description of the change to find documented rules; Read the cited lines; then judge whether the change is safe and which rules apply. Memex finds and cites; you decide.

`memex/query/models.py` changes under ADR-001 by deletion only: every remaining model keeps its fields and types, and the regenerated `tests/unit/contract_schema.json` only loses the removed entries.

## Consequences

- Six tools, each deterministic and explainable in one sentence. About 1,400 lines of code, tests and fixtures are gone, including all the stance and sentence rules.
- One-call convenience is lost: a change check now takes a few calls (`impact_of` per symbol, `search_docs`, then Read), and the agent reads whole cited sections instead of one labelled sentence each.
- Measured on q11 and q12 with the new instructions (condition B, N=1, `eval/results/phase10-workflow`): the agent followed the workflow on both. q11 F1 0.67 (Phase 7 with `check_change`: 0.55; grep only: 0.64); q12 F1 0.55 (unchanged). Input tokens 186k and 40k (Phase 7: 141k and 67k). Two questions at N=1 show the workflow is no worse; they do not prove it is better.
- The eval keeps the category name `check_change` for these two questions: it names the kind of question, not a tool.
- The Mealie smoke tests that pinned the `AppSettings` rule through `check_change` now pin it through `impact_of`'s docs and through `search_docs` on the proposal text.
- If agents prove unreliable at composing the tools on a larger eval, the next step is an MCP prompt (a named workflow the agent can load), still with no LLM in the server.
