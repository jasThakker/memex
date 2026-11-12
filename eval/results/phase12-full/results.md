# Eval run phase12-full

- Model: `claude-sonnet-5-5`, effort `high`; Claude Code `2.1.322 (Claude Code)`
- Memex commit `6f126ed1e1a9aae2ecc8fc8e1858a4dd30eeb416`; codebase commit `9552df62118224a377d9c9b0a62706a62220ab86`
- Invocations of eval/run.py: 1 (listed in meta.json)
- Runs per condition: 1 (N=1: no variance estimate)
- Score: precision, recall and F1 over the combined set of expected symbols and docs, averaged over the valid runs. A run is invalid when its init event did not offer exactly the condition's tools; its tokens still count in the usage columns.

## Summary

| Condition | Runs | Invalid | Answered | Errors | P | R | F1 | Input (all) | Uncached | Cache write | Cache read | Output | Cost USD | Turns | Time s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 12 | 0 | 12 | 0 | 0.59 | 0.82 | 0.66 | 576,299 | 96 | 117,996 | 458,207 | 24,667 | 0.76 | 88 | 185 |
| B | 12 | 0 | 12 | 0 | 0.56 | 0.76 | 0.60 | 500,481 | 96 | 107,090 | 393,295 | 18,293 | 0.65 | 79 | 141 |

## By category (P / R / F1)

| Category | A | B |
|---|---|---|
| callers | 1.00 / 1.00 / 1.00 | 0.96 / 1.00 / 0.98 |
| check_change | 0.40 / 0.75 / 0.51 | 0.38 / 0.75 / 0.50 |
| doc_rules | 0.72 / 0.79 / 0.75 | 0.80 / 0.59 / 0.63 |
| layer_domain | 0.15 / 0.40 / 0.22 | 0.08 / 0.30 / 0.13 |
| locate | 0.51 / 1.00 / 0.66 | 0.45 / 0.93 / 0.60 |

## Fixed cost per request (baseline prompt, no question)

| Condition | Input (all) | Tools offered | MCP servers | Check |
|---|---|---|---|---|
| A | 5,608 | 3 | none | ok |
| B | 5,721 | 7 | memex (connected) | ok |

Condition B's prompt is +113 input tokens larger than A's: the graph tools' definitions and server instructions, minus the Grep and Glob definitions. It is paid on every request (each turn), mostly as cache reads.

## Per question

| Question | Run | Category | Condition | F1 | P | R | Input (all) | Output | Turns | Tool calls |
|---|---|---|---|---|---|---|---|---|---|---|
| q01 | 1 | locate | A | 0.67 | 0.50 | 1.00 | 21,844 | 1,220 | 4 | Grep x2, Read x1 |
| q01 | 1 | locate | B | 0.73 | 0.57 | 1.00 | 30,533 | 1,004 | 5 | mcp__memex__find_symbol x1, mcp__memex__impact_of x1, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |
| q02 | 1 | locate | A | 0.53 | 0.36 | 1.00 | 22,791 | 1,589 | 4 | Grep x1, Read x2 |
| q02 | 1 | locate | B | 0.40 | 0.27 | 0.80 | 15,854 | 1,123 | 3 | Read x1, mcp__memex__list_codebases x1 |
| q03 | 1 | locate | A | 0.80 | 0.67 | 1.00 | 29,353 | 761 | 3 | Grep x2 |
| q03 | 1 | locate | B | 0.67 | 0.50 | 1.00 | 21,211 | 516 | 4 | mcp__memex__find_symbol x2, mcp__memex__list_codebases x1 |
| q04 | 1 | callers | A | 1.00 | 1.00 | 1.00 | 66,740 | 2,897 | 11 | Grep x8, Read x2 |
| q04 | 1 | callers | B | 1.00 | 1.00 | 1.00 | 20,919 | 956 | 3 | mcp__memex__callers x1, mcp__memex__list_codebases x1 |
| q05 | 1 | callers | A | 1.00 | 1.00 | 1.00 | 23,142 | 1,380 | 5 | Grep x2, Read x2 |
| q05 | 1 | callers | B | 0.93 | 0.88 | 1.00 | 30,171 | 1,230 | 5 | Read x1, mcp__memex__callers x1, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |
| q06 | 1 | callers | A | 1.00 | 1.00 | 1.00 | 20,295 | 1,028 | 4 | Grep x3 |
| q06 | 1 | callers | B | 1.00 | 1.00 | 1.00 | 31,098 | 1,142 | 5 | Read x2, mcp__memex__find_symbol x1, mcp__memex__list_codebases x1 |
| q07 | 1 | layer_domain | A | 0.00 | 0.00 | 0.00 | 30,604 | 2,481 | 8 | Grep x7 |
| q07 | 1 | layer_domain | B | 0.00 | 0.00 | 0.00 | 21,920 | 1,349 | 4 | mcp__memex__callers x1, mcp__memex__find_symbol x1, mcp__memex__list_codebases x1 |
| q08 | 1 | layer_domain | A | 0.44 | 0.31 | 0.80 | 38,353 | 2,567 | 9 | Grep x5, Read x3 |
| q08 | 1 | layer_domain | B | 0.26 | 0.17 | 0.60 | 55,596 | 2,599 | 11 | Read x4, mcp__memex__callers x1, mcp__memex__find_symbol x3, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |
| q09 | 1 | doc_rules | A | 1.00 | 1.00 | 1.00 | 33,250 | 1,255 | 6 | Grep x3, Read x2 |
| q09 | 1 | doc_rules | B | 0.67 | 0.60 | 0.75 | 52,095 | 1,303 | 7 | Read x3, mcp__memex__find_symbol x1, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |
| q10 | 1 | doc_rules | A | 0.50 | 0.44 | 0.57 | 55,556 | 2,104 | 9 | Glob x2, Grep x4, Read x2 |
| q10 | 1 | doc_rules | B | 0.60 | 1.00 | 0.43 | 22,814 | 872 | 4 | Read x2, mcp__memex__search_docs x1 |
| q11 | 1 | check_change | A | 0.54 | 0.47 | 0.64 | 156,063 | 4,033 | 14 | Grep x8, Read x5 |
| q11 | 1 | check_change | B | 0.50 | 0.41 | 0.64 | 155,188 | 3,869 | 19 | Read x6, mcp__memex__find_symbol x5, mcp__memex__impact_of x1, mcp__memex__list_codebases x1, mcp__memex__read_placeholder x1, mcp__memex__search_docs x4 |
| q12 | 1 | check_change | A | 0.48 | 0.33 | 0.86 | 78,308 | 3,352 | 11 | Grep x4, Read x6 |
| q12 | 1 | check_change | B | 0.50 | 0.35 | 0.86 | 43,082 | 2,330 | 9 | Read x2, mcp__memex__callers x1, mcp__memex__find_symbol x1, mcp__memex__impact_of x2, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |

## Missed and extra

### q01 A (run 1)

- extra: `mealie.schema.recipe.recipe_ingredient.RegisteredParser`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.parse`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.parse_one`
- extra: `mealie.services.parser_services.ingredient_parser.get_parser`

### q01 B (run 1)

- extra: `docs/docs/contributors/guides/ingredient-parser.md#Alternative Parsers`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.find_ingredient_match`
- extra: `mealie.services.parser_services.ingredient_parser.get_parser`

### q02 A (run 1)

- extra: `mealie.repos._utils.NOT_SET`
- extra: `mealie.repos.all_repositories.get_repositories`
- extra: `mealie.routes._base.base_controllers.BaseAdminController`
- extra: `mealie.routes._base.base_controllers.BasePublicGroupExploreController.group_id`
- extra: `mealie.routes._base.base_controllers.BasePublicHouseholdExploreController.cross_household_repos`
- extra: `mealie.routes._base.base_controllers.BaseUserController`
- extra: `mealie.routes._base.base_controllers._BaseController`
- extra: `mealie.routes._base.base_controllers._BaseController.group_id`
- extra: `mealie.routes._base.base_controllers._BaseController.household_id`

### q02 B (run 1)

- missed: `mealie.repos.repository_factory.AllRepositories`
- extra: `mealie.core.dependencies.dependencies.get_admin_user`
- extra: `mealie.core.dependencies.dependencies.get_current_user`
- extra: `mealie.db.db_setup.generate_session`
- extra: `mealie.repos.all_repositories.AllRepositories`
- extra: `mealie.routes._base.base_controllers.BaseAdminController`
- extra: `mealie.routes._base.base_controllers.BasePublicGroupExploreController`
- extra: `mealie.routes._base.base_controllers.BasePublicHouseholdExploreController.cross_household_repos`
- extra: `mealie.routes._base.base_controllers.BaseUserController`
- extra: `mealie.routes._base.base_controllers._BaseController`
- extra: `mealie.routes._base.base_controllers._BaseController.group_id`
- extra: `mealie.routes._base.base_controllers._BaseController.household_id`

### q03 A (run 1)

- extra: `mealie.routes._base.controller._cbv`

### q03 B (run 1)

- extra: `mealie.routes._base.controller`
- extra: `mealie.routes._base.mixins`

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
- extra: `mealie.repos.repository_factory.AllRepositories`
- extra: `mealie.repos.repository_factory.AllRepositories.__init__`
- extra: `mealie.repos.repository_generic.GroupRepositoryGeneric`
- extra: `mealie.repos.repository_generic.HouseholdRepositoryGeneric`
- extra: `mealie.repos.repository_generic.RepositoryGeneric`
- extra: `mealie.routes._base.base_controllers.BaseAdminController`
- extra: `mealie.routes._base.base_controllers.BasePublicHouseholdExploreController.cross_household_repos`
- extra: `mealie.routes._base.base_controllers.BaseUserController`
- extra: `mealie.routes._base.base_controllers._BaseController`

### q08 B (run 1)

- missed: `mealie.repos.repository_generic.GroupRepositoryGeneric.__init__`
- missed: `mealie.repos.repository_generic.HouseholdRepositoryGeneric.__init__`
- extra: `mealie.repos.all_repositories.AllRepositories`
- extra: `mealie.repos.repository_factory`
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
- extra: `mealie.routes._base.base_controllers.BasePublicHouseholdExploreController.cross_household_repos`
- extra: `mealie.routes._base.base_controllers.BaseUserController`
- extra: `mealie.routes._base.base_controllers._BaseController.repos`

### q09 B (run 1)

- missed: `AGENTS.md#Common Gotchas`
- extra: `AGENTS.md#Mealie Development Guide for AI Agents > Pull Request Best Practices > What to Review`
- extra: `mealie.repos.repository_factory.AllRepositories`

### q10 A (run 1)

- missed: `AGENTS.md#Backend Architecture (mealie/)`
- missed: `AGENTS.md#Essential Commands (via Task/Taskfile.yml)`
- missed: `AGENTS.md#Frontend`
- extra: `dev.code-generation.gen_py_pytest_data_paths`
- extra: `dev.code-generation.gen_py_pytest_routes`
- extra: `dev.code-generation.gen_py_schema_exports`
- extra: `dev.code-generation.gen_ts_types`
- extra: `dev.code-generation.main`

### q10 B (run 1)

- missed: `AGENTS.md#Backend Architecture (mealie/)`
- missed: `AGENTS.md#Essential Commands (via Task/Taskfile.yml)`
- missed: `AGENTS.md#Frontend`
- missed: `AGENTS.md#What to Review`

### q11 A (run 1)

- missed: `AGENTS.md#Cross-Cutting Concerns`
- missed: `AGENTS.md#What to Review`
- missed: `docs/docs/contributors/developers-guide/code-contributions.md#We Use GitHub Flow, So All Code Changes Happen Through Pull Requests`
- missed: `mealie.schema.group.ai_providers.AIProviderCreate.validate_as_none`
- extra: `docs/docs/contributors/developers-guide/migration-guide.md#`updateAt` is now `updatedAt``
- extra: `docs/docs/documentation/getting-started/installation/ai-providers.md#Configuration`
- extra: `mealie.alembic.versions.2026-05-18-16.27.05_2187537c52b8_add_table_for_ai_providers`
- extra: `mealie.repos.repository_ai_provider.GroupRepositoryAIProvider`
- extra: `mealie.schema.group.ai_providers.AIProviderOut`
- extra: `mealie.schema.group.ai_providers.AIProviderSave`
- extra: `mealie.schema.group.ai_providers.AIProviderUpdate`
- extra: `mealie.services.openai.openai.OpenAIService.test_connection`

### q11 B (run 1)

- missed: `docs/docs/contributors/developers-guide/code-contributions.md#We Use GitHub Flow, So All Code Changes Happen Through Pull Requests`
- missed: `mealie.routes.groups.controller_group_ai_providers.GroupAIProviderController.test_ai_provider`
- missed: `mealie.routes.groups.controller_group_ai_providers.GroupAIProviderController.test_saved_ai_provider`
- missed: `mealie.schema.group.ai_providers.AIProviderCreate.validate_as_none`
- extra: `AGENTS.md#Common Gotchas`
- extra: `AGENTS.md#Essential Commands (via Task/Taskfile.yml)`
- extra: `mealie.repos.repository_ai_provider.GroupRepositoryAIProvider`
- extra: `mealie.routes.admin.admin_debug.AdminDebugController.debug_openai`
- extra: `mealie.routes.admin.admin_management_ai_providers.AdminGroupAIProviderController`
- extra: `mealie.routes.groups.controller_group_ai_providers.GroupAIProviderController`
- extra: `mealie.schema.group.ai_providers.AIProviderOut`
- extra: `mealie.schema.group.ai_providers.AIProviderSave`
- extra: `mealie.schema.group.ai_providers.AIProviderUpdate`
- extra: `mealie.services.openai.openai.OpenAIService.test_connection`

### q12 A (run 1)

- missed: `AGENTS.md#Cross-Cutting Concerns`
- extra: `docs/docs/contributors/guides/ingredient-parser.md#Improving the Ingredient Parser`
- extra: `mealie.schema.recipe.recipe_ingredient.IngredientRequest`
- extra: `mealie.schema.recipe.recipe_ingredient.IngredientsRequest`
- extra: `mealie.services.parser_services`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.find_ingredient_match`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.parse`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.parse_one`
- extra: `mealie.services.parser_services._base.DataMatcher`
- extra: `mealie.services.parser_services.ingredient_parser.BruteForceParser`
- extra: `mealie.services.parser_services.ingredient_parser.NLPParser`
- extra: `mealie.services.parser_services.ingredient_parser.__registrar`
- extra: `mealie.services.parser_services.openai.parser`

### q12 B (run 1)

- missed: `AGENTS.md#Cross-Cutting Concerns`
- extra: `docs/docs/contributors/guides/ingredient-parser.md#Improving the Ingredient Parser`
- extra: `docs/docs/documentation/getting-started/installation/ai-providers.md#AI Features`
- extra: `mealie.schema.recipe.recipe_ingredient.IngredientRequest`
- extra: `mealie.schema.recipe.recipe_ingredient.IngredientsRequest`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.find_ingredient_match`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.parse`
- extra: `mealie.services.parser_services._base.ABCIngredientParser.parse_one`
- extra: `mealie.services.parser_services.ingredient_parser`
- extra: `mealie.services.parser_services.ingredient_parser.BruteForceParser`
- extra: `mealie.services.parser_services.ingredient_parser.NLPParser`
- extra: `mealie.services.parser_services.openai.parser.OpenAIParser`
