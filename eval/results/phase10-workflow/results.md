# Eval run phase10-workflow

- Model: `claude-sonnet-5-5`, effort `high`; Claude Code `2.1.319 (Claude Code)`
- Memex commit `a793c81d251f0c4f2169e2db75a4fab3257c0eb7-dirty`; codebase commit `9552df62118224a377d9c9b0a62706a62220ab86`
- Invocations of eval/run.py: 1 (listed in meta.json)
- Runs per condition: 1 (N=1: no variance estimate)
- Score: precision, recall and F1 over the combined set of expected symbols and docs, averaged over the valid runs. A run is invalid when its init event did not offer exactly the condition's tools; its tokens still count in the usage columns.

## Summary

| Condition | Runs | Invalid | Answered | Errors | P | R | F1 | Input (all) | Uncached | Cache write | Cache read | Output | Cost USD | Turns | Time s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B | 2 | 0 | 2 | 0 | 0.51 | 0.79 | 0.61 | 225,910 | 26 | 46,159 | 179,725 | 6,324 | 0.27 | 30 | 61 |

## By category (P / R / F1)

| Category | B |
|---|---|
| check_change | 0.51 / 0.79 / 0.61 |

## Per question

| Question | Run | Category | Condition | F1 | P | R | Input (all) | Output | Turns | Tool calls |
|---|---|---|---|---|---|---|---|---|---|---|
| q11 | 1 | check_change | B | 0.67 | 0.62 | 0.73 | 186,356 | 4,015 | 20 | Read x8, mcp__memex__callers x1, mcp__memex__find_symbol x5, mcp__memex__impact_of x1, mcp__memex__list_codebases x1, mcp__memex__search_docs x3 |
| q12 | 1 | check_change | B | 0.55 | 0.40 | 0.86 | 39,554 | 2,309 | 10 | Read x2, mcp__memex__callers x1, mcp__memex__find_symbol x2, mcp__memex__impact_of x2, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |

## Missed and extra

### q11 B (run 1)

- missed: `docs/docs/contributors/developers-guide/code-contributions.md#We Use GitHub Flow, So All Code Changes Happen Through Pull Requests`
- missed: `docs/docs/contributors/developers-guide/database-changes.md#Overview`
- missed: `mealie.schema.group.ai_providers.AIProviderCreate.validate_as_none`
- extra: `AGENTS.md#Common Gotchas`
- extra: `docs/docs/documentation/getting-started/installation/ai-providers.md#Configuration`
- extra: `mealie.repos.repository_ai_provider.GroupRepositoryAIProvider`
- extra: `mealie.schema.group.ai_providers.AIProviderOut`
- extra: `mealie.services.openai.openai.OpenAIService.test_connection`

### q12 B (run 1)

- missed: `AGENTS.md#Cross-Cutting Concerns`
- extra: `docs/docs/contributors/guides/ingredient-parser.md#Improving The CRF Parser`
- extra: `docs/docs/contributors/guides/ingredient-parser.md#Improving the Ingredient Parser`
- extra: `docs/docs/documentation/getting-started/installation/ai-providers.md#AI Features`
- extra: `mealie.schema.recipe.recipe_ingredient.IngredientRequest`
- extra: `mealie.schema.recipe.recipe_ingredient.IngredientsRequest`
- extra: `mealie.services.parser_services.ingredient_parser`
- extra: `mealie.services.parser_services.ingredient_parser.BruteForceParser`
- extra: `mealie.services.parser_services.ingredient_parser.NLPParser`
- extra: `mealie.services.parser_services.openai.parser.OpenAIParser`
