# ADR-002: check_change finds and labels rules without an LLM

- Status: accepted; the `check_change` tool was removed by ADR-004, and the principle (no LLM in the server) stands
- Date: 2026-11-05 (Phase 6)

## Context

`check_change` tells an agent, before it makes a change, which code the change affects and which of the team's documented rules apply. Deciding whether a rule applies, and whether it forbids or encourages the change, is a judgment about natural language. Two ways to make it:

- **An LLM inside the server** reads the candidate doc sections and the proposal and decides. It understands paraphrase and context, but the server then needs a model, an API key and network access. Its answers vary between runs, cost money per call, and are hard to test against known answers.
- **Retrieval plus transparent rules** in the server, with the calling agent, which is already an LLM, making the final judgment from quoted, cited sentences.

## Decision

`check_change` does not call an LLM. It does three things, all deterministic:

- **Resolves the proposal** with the symbol rule shared by every tool. A short name that matches several symbols is returned as ambiguous with its candidates, never guessed.
- **Retrieves candidate rules** from two sources:
  - **mention:** doc sections that MENTION the affected code (the resolved symbols, their members, their dependents, and the modules and packages enclosing them).
  - **search:** a full-text search on the description, which finds rules that name no symbol.
- **Labels each quoted sentence** with a stance from modal verbs: `never`, `do not`, `must not`, `avoid` and similar give `forbids`; `must`, `should`, `always`, `prefer` give `encourages`; a negated requirement ("you don't need to") or anything else gives `related`.

Every guideline is one sentence, cited by path, heading path and the sentence's own lines, so the agent can read the source and overrule the label. The tool description says the stance is a hint.

The rules are listed in DESIGN.md section 10; their known blind spots are in section 13.

## Consequences

- The server stays read-only, offline, free per call and reproducible. Every rule is tested against fixtures with known sentences, line ranges and stances.
- The labels miss meaning that is not in the modal verbs. Examples:
  - a rule phrased without one ("Routes call services") is `related`
  - a sentence with both a requirement and a prohibition is labeled `forbids`
  - search can match a sentence on a generic shared word

  The agent is expected to read the quotes; the eval in Phase 7 measures whether that is enough.
- Changing the retrieval or the stance rules needs no new dependency. Adding an LLM later would be a new ADR, and would sit beside these rules, not replace the citations.
