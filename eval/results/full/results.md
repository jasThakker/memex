# Eval run full

- Model: `claude-sonnet-5-5`, effort `high`; Claude Code `2.1.318 (Claude Code)`
- Memex commit `7589ac190e80a1c32737b7fad377ddf748149ce5`; codebase commit `9552df62118224a377d9c9b0a62706a62220ab86`
- Invocations of eval/run.py: 1 (listed in meta.json)
- Runs per condition: 1 (N=1: no variance estimate)
- Score: precision, recall and F1 over the combined set of expected symbols and docs, averaged over the valid runs. A run is invalid when its init event did not offer exactly the condition's tools; its tokens still count in the usage columns.

## Summary

| Condition | Runs | Invalid | Answered | Errors | P | R | F1 | Input (all) | Uncached | Cache write | Cache read | Output | Cost USD | Turns | Time s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 12 | 0 | 12 | 0 | 0.64 | 0.79 | 0.68 | 501,869 | 90 | 110,685 | 391,094 | 23,036 | 0.71 | 80 | 177 |
| B | 12 | 0 | 12 | 0 | 0.54 | 0.76 | 0.60 | 701,473 | 114 | 132,304 | 569,055 | 21,151 | 0.80 | 97 | 180 |

## By category (P / R / F1)

| Category | A | B |
|---|---|---|
| callers | 0.92 / 1.00 / 0.96 | 0.96 / 1.00 / 0.98 |
| check_change | 0.49 / 0.79 / 0.59 | 0.42 / 0.79 / 0.55 |
| doc_rules | 1.00 / 0.86 / 0.92 | 0.62 / 0.59 / 0.57 |
| layer_domain | 0.05 / 0.20 / 0.08 | 0.07 / 0.30 / 0.11 |
| locate | 0.60 / 0.93 / 0.70 | 0.44 / 0.93 / 0.59 |

## Fixed cost per request (baseline prompt, no question)

| Condition | Input (all) | Tools offered | MCP servers | Check |
|---|---|---|---|---|
| A | 5,518 | 3 | none | ok |
| B | 5,983 | 8 | memex (connected) | ok |

Condition B's prompt is +465 input tokens larger than A's: the graph tools' definitions and server instructions, minus the Grep and Glob definitions. It is paid on every request (each turn), mostly as cache reads.

## Per question

| Question | Run | Category | Condition | F1 | P | R | Input (all) | Output | Turns | Tool calls |
|---|---|---|---|---|---|---|---|---|---|---|
| q01 | 1 | locate | A | 0.67 | 0.50 | 1.00 | 31,714 | 1,466 | 5 | Grep x4 |
| q01 | 1 | locate | B | 0.73 | 0.57 | 1.00 | 22,534 | 891 | 4 | mcp__memex__find_symbol x1, mcp__memex__impact_of x1, mcp__memex__list_codebases x1 |
| q02 | 1 | locate | A | 0.44 | 0.31 | 0.80 | 23,491 | 1,457 | 4 | Grep x2, Read x1 |
| q02 | 1 | locate | B | 0.38 | 0.25 | 0.80 | 24,261 | 1,296 | 5 | Read x1, mcp__memex__find_symbol x2, mcp__memex__list_codebases x1 |
| q03 | 1 | locate | A | 1.00 | 1.00 | 1.00 | 12,325 | 471 | 2 | Grep x1 |
| q03 | 1 | locate | B | 0.67 | 0.50 | 1.00 | 21,947 | 533 | 4 | mcp__memex__find_symbol x2, mcp__memex__list_codebases x1 |
| q04 | 1 | callers | A | 0.93 | 0.88 | 1.00 | 32,235 | 2,347 | 8 | Grep x7 |
| q04 | 1 | callers | B | 1.00 | 1.00 | 1.00 | 159,655 | 3,117 | 14 | Read x3, mcp__memex__callers x4, mcp__memex__find_symbol x4, mcp__memex__impact_of x1, mcp__memex__list_codebases x1 |
| q05 | 1 | callers | A | 0.93 | 0.88 | 1.00 | 22,844 | 1,493 | 5 | Grep x4 |
| q05 | 1 | callers | B | 0.93 | 0.88 | 1.00 | 21,554 | 744 | 3 | mcp__memex__callers x1, mcp__memex__list_codebases x1 |
| q06 | 1 | callers | A | 1.00 | 1.00 | 1.00 | 20,971 | 1,033 | 4 | Grep x3 |
| q06 | 1 | callers | B | 1.00 | 1.00 | 1.00 | 37,771 | 1,359 | 6 | Grep x1, Read x2, mcp__memex__impact_of x1, mcp__memex__list_codebases x1 |
| q07 | 1 | layer_domain | A | 0.00 | 0.00 | 0.00 | 29,936 | 2,499 | 8 | Grep x7 |
| q07 | 1 | layer_domain | B | 0.00 | 0.00 | 0.00 | 22,656 | 1,254 | 4 | mcp__memex__callers x1, mcp__memex__find_symbol x1, mcp__memex__list_codebases x1 |
| q08 | 1 | layer_domain | A | 0.17 | 0.11 | 0.40 | 69,444 | 3,208 | 11 | Grep x6, Read x4 |
| q08 | 1 | layer_domain | B | 0.22 | 0.14 | 0.60 | 119,354 | 3,566 | 17 | Grep x1, Read x8, mcp__memex__callees x1, mcp__memex__find_symbol x4, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |
| q09 | 1 | doc_rules | A | 1.00 | 1.00 | 1.00 | 32,097 | 1,189 | 6 | Grep x3, Read x2 |
| q09 | 1 | doc_rules | B | 0.60 | 0.50 | 0.75 | 40,907 | 1,075 | 7 | Read x2, mcp__memex__find_symbol x2, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |
| q10 | 1 | doc_rules | A | 0.83 | 1.00 | 0.71 | 41,006 | 1,239 | 5 | Grep x3, Read x1 |
| q10 | 1 | doc_rules | B | 0.55 | 0.75 | 0.43 | 23,277 | 713 | 3 | Read x1, mcp__memex__search_docs x1 |
| q11 | 1 | check_change | A | 0.64 | 0.57 | 0.73 | 102,858 | 3,725 | 12 | Grep x5, Read x6 |
| q11 | 1 | check_change | B | 0.55 | 0.44 | 0.73 | 140,773 | 3,739 | 17 | Read x5, mcp__memex__check_change x1, mcp__memex__find_symbol x6, mcp__memex__list_codebases x1, mcp__memex__search_docs x3 |
| q12 | 1 | check_change | A | 0.55 | 0.40 | 0.86 | 82,948 | 2,909 | 10 | Grep x3, Read x6 |
| q12 | 1 | check_change | B | 0.55 | 0.40 | 0.86 | 66,784 | 2,864 | 13 | Read x5, mcp__memex__callers x1, mcp__memex__find_symbol x2, mcp__memex__impact_of x1, mcp__memex__list_codebases x1, mcp__memex__search_docs x2 |

## Missed and extra

### q01 A (run 1)

- extra: `docs/docs/contributors/guides/ingredient-parser.md#Alternative Parsers`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.parse`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.parse_one`
- extra: `mealie.services.parser_services.ingredient_parser.get_parser`

### q01 B (run 1)

- extra: `docs/docs/contributors/guides/ingredient-parser.md#Alternative Parsers`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.find_ingredient_match`
- extra: `mealie.services.parser_services.ingredient_parser.get_parser`

### q02 A (run 1)

- missed: `mealie.repos.repository_factory.AllRepositories`
- extra: `mealie.core.dependencies.dependencies.get_admin_user`
- extra: `mealie.core.dependencies.dependencies.get_current_user`
- extra: `mealie.repos.all_repositories.AllRepositories`
- extra: `mealie.repos.all_repositories.get_repositories`
- extra: `mealie.routes._base.base_controllers.BaseAdminController`
- extra: `mealie.routes._base.base_controllers.BaseUserController`
- extra: `mealie.routes._base.base_controllers._BaseController`
- extra: `mealie.routes._base.base_controllers._BaseController.group_id`
- extra: `mealie.routes._base.base_controllers._BaseController.household_id`

### q02 B (run 1)

- missed: `mealie.repos.repository_factory.AllRepositories`
- extra: `mealie.core.dependencies.dependencies.get_admin_user`
- extra: `mealie.core.dependencies.dependencies.get_current_user`
- extra: `mealie.db.db_setup.generate_session`
- extra: `mealie.repos._utils.NOT_SET`
- extra: `mealie.repos.all_repositories.AllRepositories`
- extra: `mealie.routes._base.base_controllers.BaseAdminController`
- extra: `mealie.routes._base.base_controllers.BaseUserController`
- extra: `mealie.routes._base.base_controllers.BaseUserController.group`
- extra: `mealie.routes._base.base_controllers.BaseUserController.household`
- extra: `mealie.routes._base.base_controllers._BaseController`
- extra: `mealie.routes._base.base_controllers._BaseController.group_id`
- extra: `mealie.routes._base.base_controllers._BaseController.household_id`

### q03 B (run 1)

- extra: `mealie.routes._base.controller`
- extra: `mealie.routes._base.mixins`

### q04 A (run 1)

- extra: `mealie.services.recipe.recipe_service.RecipeService.create_one`

### q05 A (run 1)

- extra: `mealie.services.parser_services._base.DataMatcher`

### q05 B (run 1)

- extra: `mealie.services.parser_services._base.DataMatcher`

### q07 A (run 1)

- missed: `mealie.routes.admin.admin_debug`
- missed: `mealie.routes.admin.admin_management_ai_providers`
- missed: `mealie.routes.groups.controller_group_ai_providers`
- missed: `mealie.services.parser_services.openai.parser`
- missed: `mealie.services.recipe.ai_recipe_service`
- missed: `mealie.services.scraper.scraper_strategies`
- extra: `mealie.routes.admin.admin_debug.AdminDebugController.debug_openai`
- extra: `mealie.routes.admin.admin_management_ai_providers.AdminGroupAIProviderController.delete_ai_prompt`
- extra: `mealie.routes.admin.admin_management_ai_providers.AdminGroupAIProviderController.get_ai_prompts`
- extra: `mealie.routes.admin.admin_management_ai_providers.AdminGroupAIProviderController.update_ai_prompt`
- extra: `mealie.routes.groups.controller_group_ai_providers.GroupAIPromptController.service`
- extra: `mealie.routes.groups.controller_group_ai_providers.GroupAIProviderController.test_ai_provider`
- extra: `mealie.routes.groups.controller_group_ai_providers.GroupAIProviderController.test_saved_ai_provider`
- extra: `mealie.services.openai.openai.OpenAIService`
- extra: `mealie.services.parser_services.openai.parser.OpenAIParser._parse`
- extra: `mealie.services.recipe.ai_recipe_service.AIRecipeService.build_recipe`
- extra: `mealie.services.scraper.scraper_strategies.RecipeScraperOpenAI.build_context`
- extra: `mealie.services.scraper.scraper_strategies.RecipeScraperOpenAITranscription.parse`

### q07 B (run 1)

- missed: `mealie.routes.admin.admin_debug`
- missed: `mealie.routes.admin.admin_management_ai_providers`
- missed: `mealie.routes.groups.controller_group_ai_providers`
- missed: `mealie.services.parser_services.openai.parser`
- missed: `mealie.services.recipe.ai_recipe_service`
- missed: `mealie.services.scraper.scraper_strategies`
- extra: `mealie.routes.admin.admin_debug.AdminDebugController.debug_openai`
- extra: `mealie.routes.admin.admin_management_ai_providers.AdminGroupAIProviderController.delete_ai_prompt`
- extra: `mealie.routes.admin.admin_management_ai_providers.AdminGroupAIProviderController.get_ai_prompts`
- extra: `mealie.routes.admin.admin_management_ai_providers.AdminGroupAIProviderController.update_ai_prompt`
- extra: `mealie.routes.groups.controller_group_ai_providers.GroupAIPromptController.service`
- extra: `mealie.routes.groups.controller_group_ai_providers.GroupAIProviderController.test_ai_provider`
- extra: `mealie.routes.groups.controller_group_ai_providers.GroupAIProviderController.test_saved_ai_provider`
- extra: `mealie.services.openai.openai.OpenAIService`
- extra: `mealie.services.parser_services.openai.parser.OpenAIParser._parse`
- extra: `mealie.services.recipe.ai_recipe_service.AIRecipeService.build_recipe`
- extra: `mealie.services.scraper.scraper_strategies.RecipeScraperOpenAI.build_context`
- extra: `mealie.services.scraper.scraper_strategies.RecipeScraperOpenAITranscription.parse`

### q08 A (run 1)

- missed: `AGENTS.md#Cross-Cutting Concerns`
- missed: `mealie.repos.repository_generic.GroupRepositoryGeneric.__init__`
- missed: `mealie.repos.repository_generic.HouseholdRepositoryGeneric.__init__`
- extra: `mealie.repos.repository_factory.AllRepositories`
- extra: `mealie.repos.repository_generic.GroupRepositoryGeneric`
- extra: `mealie.repos.repository_generic.HouseholdRepositoryGeneric`
- extra: `mealie.repos.repository_generic.RepositoryGeneric`
- extra: `mealie.repos.repository_generic.RepositoryGeneric._query`
- extra: `mealie.repos.repository_generic.RepositoryGeneric.delete`
- extra: `mealie.repos.repository_generic.RepositoryGeneric.delete_many`
- extra: `mealie.repos.repository_generic.RepositoryGeneric.get_all`
- extra: `mealie.repos.repository_generic.RepositoryGeneric.get_one`
- extra: `mealie.repos.repository_generic.RepositoryGeneric.multi_query`
- extra: `mealie.repos.repository_generic.RepositoryGeneric.page_all`
- extra: `mealie.routes._base.base_controllers.BaseAdminController`
- extra: `mealie.routes._base.base_controllers.BasePublicHouseholdExploreController.cross_household_repos`
- extra: `mealie.routes._base.base_controllers.BaseUserController`
- extra: `mealie.routes._base.base_controllers.BaseUserController.group_id`
- extra: `mealie.routes._base.base_controllers.BaseUserController.household_id`
- extra: `mealie.routes._base.base_controllers._BaseController.repos`

### q08 B (run 1)

- missed: `mealie.repos.repository_generic.GroupRepositoryGeneric.__init__`
- missed: `mealie.repos.repository_generic.HouseholdRepositoryGeneric.__init__`
- extra: `mealie.repos._recipe_suggestions.RecipeSuggestionMixin._filter_builder`
- extra: `mealie.repos.all_repositories.get_repositories`
- extra: `mealie.repos.repository_factory.AllRepositories`
- extra: `mealie.repos.repository_factory.AllRepositories.__init__`
- extra: `mealie.repos.repository_generic.GroupRepositoryGeneric`
- extra: `mealie.repos.repository_generic.HouseholdRepositoryGeneric`
- extra: `mealie.repos.repository_generic.RepositoryGeneric`
- extra: `mealie.repos.repository_generic.RepositoryGeneric._query_one`
- extra: `mealie.repos.repository_generic.RepositoryGeneric.delete_many`
- extra: `mealie.repos.repository_generic.RepositoryGeneric.get_one`
- extra: `mealie.repos.repository_generic.RepositoryGeneric.multi_query`
- extra: `mealie.repos.repository_generic.RepositoryGeneric.page_all`
- extra: `mealie.repos.repository_generic.RepositoryGeneric.update_many`
- extra: `mealie.routes._base.base_controllers.BaseAdminController`
- extra: `mealie.routes._base.base_controllers.BasePublicGroupExploreController`
- extra: `mealie.routes._base.base_controllers.BasePublicHouseholdExploreController.cross_household_repos`
- extra: `mealie.routes._base.base_controllers.BaseUserController`
- extra: `mealie.routes._base.base_controllers._BaseController`
- extra: `mealie.routes._base.base_controllers._BaseController.repos`

### q09 B (run 1)

- missed: `AGENTS.md#Backend Architecture (mealie/)`
- extra: `AGENTS.md#Database & Sessions`
- extra: `AGENTS.md#What to Review`
- extra: `mealie.repos.repository_factory.AllRepositories`

### q10 A (run 1)

- missed: `AGENTS.md#Backend Architecture (mealie/)`
- missed: `AGENTS.md#Frontend`

### q10 B (run 1)

- missed: `AGENTS.md#Backend Architecture (mealie/)`
- missed: `AGENTS.md#Before Submitting a PR`
- missed: `AGENTS.md#Essential Commands (via Task/Taskfile.yml)`
- missed: `AGENTS.md#Frontend`
- extra: `mealie.schema`

### q11 A (run 1)

- missed: `AGENTS.md#What to Review`
- missed: `docs/docs/contributors/developers-guide/code-contributions.md#We Use GitHub Flow, So All Code Changes Happen Through Pull Requests`
- missed: `docs/docs/contributors/developers-guide/database-changes.md#Overview`
- extra: `AGENTS.md#Common Gotchas`
- extra: `AGENTS.md#Database Changes`
- extra: `docs/docs/documentation/getting-started/installation/ai-providers.md#Configuration`
- extra: `mealie.alembic.versions.2026-05-18-16.27.05_2187537c52b8_add_table_for_ai_providers`
- extra: `mealie.schema.group.ai_providers.AIProviderOut`
- extra: `mealie.services.openai.openai.OpenAIService.test_connection`

### q11 B (run 1)

- missed: `AGENTS.md#What to Review`
- missed: `docs/docs/contributors/developers-guide/code-contributions.md#We Use GitHub Flow, So All Code Changes Happen Through Pull Requests`
- missed: `docs/docs/contributors/developers-guide/database-changes.md#Overview`
- extra: `AGENTS.md#Backend Architecture (mealie/)`
- extra: `docs/docs/contributors/developers-guide/database-changes.md#Development: Database Changes`
- extra: `docs/docs/documentation/getting-started/installation/ai-providers.md#Configuration`
- extra: `mealie.repos.repository_ai_provider.GroupRepositoryAIProvider`
- extra: `mealie.routes.admin.admin_debug.AdminDebugController.debug_openai`
- extra: `mealie.routes.admin.admin_management_ai_providers.AdminGroupAIProviderController`
- extra: `mealie.schema.group.ai_providers.AIProviderOut`
- extra: `mealie.schema.group.ai_providers.AIProviderSave`
- extra: `mealie.schema.group.ai_providers.AIProviderUpdate`
- extra: `mealie.services.openai.openai.OpenAIService.test_connection`

### q12 A (run 1)

- missed: `AGENTS.md#Cross-Cutting Concerns`
- extra: `docs/docs/contributors/guides/ingredient-parser.md#Improving the Ingredient Parser`
- extra: `mealie.schema.recipe.recipe_ingredient.IngredientRequest`
- extra: `mealie.schema.recipe.recipe_ingredient.IngredientsRequest`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.find_ingredient_match`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.parse`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.parse_one`
- extra: `mealie.services.parser_services.ingredient_parser.BruteForceParser`
- extra: `mealie.services.parser_services.ingredient_parser.NLPParser`
- extra: `mealie.services.parser_services.openai.parser.OpenAIParser`

### q12 B (run 1)

- missed: `AGENTS.md#Cross-Cutting Concerns`
- extra: `docs/docs/contributors/guides/ingredient-parser.md#Improving The CRF Parser`
- extra: `docs/docs/documentation/getting-started/installation/ai-providers.md#AI Features`
- extra: `mealie.schema.recipe.recipe_ingredient.IngredientRequest`
- extra: `mealie.schema.recipe.recipe_ingredient.IngredientsRequest`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.parse`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.parse_one`
- extra: `mealie.services.parser_services.ingredient_parser.BruteForceParser`
- extra: `mealie.services.parser_services.ingredient_parser.NLPParser`
- extra: `mealie.services.parser_services.openai.parser.OpenAIParser`
