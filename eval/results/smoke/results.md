# Eval run smoke

- Model: `claude-sonnet-5-5`, effort `high`; Claude Code `2.1.318 (Claude Code)`
- Memex commit `7589ac190e80a1c32737b7fad377ddf748149ce5`; codebase commit `9552df62118224a377d9c9b0a62706a62220ab86`
- Invocations of eval/run.py: 2 (listed in meta.json)
- Runs per condition: 1 (N=1: no variance estimate)
- Score: precision, recall and F1 over the combined set of expected symbols and docs, averaged over the valid runs. A run is invalid when its init event did not offer exactly the condition's tools; its tokens still count in the usage columns.

## Summary

| Condition | Runs | Invalid | Answered | Errors | P | R | F1 | Input (all) | Uncached | Cache write | Cache read | Output | Cost USD | Turns | Time s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B | 1 | 0 | 1 | 0 | 0.44 | 0.64 | 0.52 | 231,809 | 22 | 30,928 | 200,859 | 4,670 | 0.19 | 24 | 39 |

## By category (P / R / F1)

| Category | B |
|---|---|
| check_change | 0.44 / 0.64 / 0.52 |

## Fixed cost per request (baseline prompt, no question)

| Condition | Input (all) | Tools offered | MCP servers | Check |
|---|---|---|---|---|
| A | 5,524 | 3 | none | ok |
| B | 5,989 | 8 | memex (connected) | ok |

Condition B's prompt is +465 input tokens larger than A's: the graph tools' definitions and server instructions, minus the Grep and Glob definitions. It is paid on every request (each turn), mostly as cache reads.

## Per question

| Question | Run | Category | Condition | F1 | P | R | Input (all) | Output | Turns | Tool calls |
|---|---|---|---|---|---|---|---|---|---|---|
| q11 | 1 | check_change | B | 0.52 | 0.44 | 0.64 | 231,809 | 4,670 | 24 | Read x9, mcp__memex__callers x1, mcp__memex__check_change x1, mcp__memex__find_symbol x7, mcp__memex__impact_of x1, mcp__memex__list_codebases x1, mcp__memex__search_docs x3 |

## Missed and extra

### q11 B (run 1)

- missed: `AGENTS.md#What to Review`
- missed: `docs/docs/contributors/developers-guide/code-contributions.md#We Use GitHub Flow, So All Code Changes Happen Through Pull Requests`
- missed: `docs/docs/contributors/developers-guide/database-changes.md#Overview`
- missed: `mealie.schema.group.ai_providers.AIProviderCreate.validate_as_none`
- extra: `AGENTS.md#Common Gotchas`
- extra: `AGENTS.md#Pull Request Best Practices`
- extra: `docs/docs/documentation/getting-started/installation/ai-providers.md#Configuration`
- extra: `mealie.repos.repository_ai_provider.GroupRepositoryAIProvider`
- extra: `mealie.routes.admin.admin_management_ai_providers.AdminGroupAIProviderController`
- extra: `mealie.schema.group.ai_providers.AIProviderOut`
- extra: `mealie.schema.group.ai_providers.AIProviderSave`
- extra: `mealie.schema.group.ai_providers.AIProviderUpdate`
- extra: `mealie.services.openai.openai.OpenAIService.test_connection`
