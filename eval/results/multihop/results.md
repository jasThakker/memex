# Eval run multihop

- Model: `claude-sonnet-5-5`, effort `high`; Claude Code `2.1.322 (Claude Code)`
- Memex commit `5396db948ee160f01e610ee930865bea5ca600d8`; codebase commit `9552df62118224a377d9c9b0a62706a62220ab86`
- Invocations of eval/run.py: 1 (listed in meta.json)
- Runs per condition: 3
- Score: precision, recall and F1 over the combined set of expected symbols and docs, averaged over the valid runs. A run is invalid when its init event did not offer exactly the condition's tools; its tokens still count in the usage columns.

## Summary

| Condition | Runs | Invalid | Answered | Errors | P | R | F1 | Input (all) | Uncached | Cache write | Cache read | Output | Cost USD | Turns | Time s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 24 | 0 | 24 | 0 | 0.97 | 1.00 | 0.98 | 1,997,618 | 282 | 350,099 | 1,647,237 | 79,122 | 2.36 | 269 | 609 |
| B | 24 | 0 | 24 | 0 | 0.99 | 0.99 | 0.99 | 1,224,248 | 228 | 207,638 | 1,016,382 | 44,345 | 1.38 | 164 | 330 |

## By category (P / R / F1)

| Category | A | B |
|---|---|---|
| multi_hop | 0.97 / 1.00 / 0.98 | 0.99 / 0.99 / 0.99 |

## Fixed cost per request (baseline prompt, no question)

| Condition | Input (all) | Tools offered | MCP servers | Check |
|---|---|---|---|---|
| A | 5,602 | 3 | none | ok |
| B | 5,715 | 7 | memex (connected) | ok |

Condition B's prompt is +113 input tokens larger than A's: the graph tools' definitions and server instructions, minus the Grep and Glob definitions. It is paid on every request (each turn), mostly as cache reads.

## Per question

| Question | Run | Category | Condition | F1 | P | R | Input (all) | Output | Turns | Tool calls |
|---|---|---|---|---|---|---|---|---|---|---|
| m01 | 1 | multi_hop | A | 1.00 | 1.00 | 1.00 | 79,151 | 2,742 | 13 | Grep x3, Read x9 |
| m01 | 2 | multi_hop | A | 1.00 | 1.00 | 1.00 | 75,101 | 2,689 | 12 | Grep x3, Read x8 |
| m01 | 3 | multi_hop | A | 1.00 | 1.00 | 1.00 | 108,669 | 3,270 | 14 | Grep x4, Read x9 |
| m01 | 1 | multi_hop | B | 0.96 | 1.00 | 0.92 | 21,389 | 840 | 3 | mcp__memex__callers x1, mcp__memex__list_codebases x1 |
| m01 | 2 | multi_hop | B | 0.96 | 1.00 | 0.92 | 21,389 | 798 | 3 | mcp__memex__callers x1, mcp__memex__list_codebases x1 |
| m01 | 3 | multi_hop | B | 0.96 | 1.00 | 0.92 | 21,389 | 810 | 3 | mcp__memex__callers x1, mcp__memex__list_codebases x1 |
| m02 | 1 | multi_hop | A | 0.95 | 0.95 | 0.95 | 112,018 | 4,467 | 14 | Grep x7, Read x6 |
| m02 | 2 | multi_hop | A | 1.00 | 1.00 | 1.00 | 140,767 | 5,208 | 13 | Grep x8, Read x4 |
| m02 | 3 | multi_hop | A | 1.00 | 1.00 | 1.00 | 144,036 | 5,085 | 14 | Grep x8, Read x5 |
| m02 | 1 | multi_hop | B | 1.00 | 1.00 | 1.00 | 89,968 | 3,222 | 12 | Read x2, mcp__memex__callers x4, mcp__memex__find_symbol x2, mcp__memex__impact_of x1, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |
| m02 | 2 | multi_hop | B | 1.00 | 1.00 | 1.00 | 165,465 | 4,034 | 17 | Read x5, mcp__memex__callers x5, mcp__memex__find_symbol x3, mcp__memex__impact_of x2, mcp__memex__list_codebases x1 |
| m02 | 3 | multi_hop | B | 1.00 | 1.00 | 1.00 | 101,089 | 3,468 | 11 | Read x2, mcp__memex__callers x4, mcp__memex__find_symbol x1, mcp__memex__impact_of x2, mcp__memex__list_codebases x1 |
| m03 | 1 | multi_hop | A | 0.79 | 0.65 | 1.00 | 108,461 | 4,603 | 13 | Grep x5, Read x7 |
| m03 | 2 | multi_hop | A | 1.00 | 1.00 | 1.00 | 72,420 | 3,582 | 11 | Grep x3, Read x7 |
| m03 | 3 | multi_hop | A | 1.00 | 1.00 | 1.00 | 90,680 | 3,782 | 13 | Grep x5, Read x7 |
| m03 | 1 | multi_hop | B | 0.96 | 0.93 | 1.00 | 34,840 | 1,569 | 3 | mcp__memex__impact_of x1, mcp__memex__list_codebases x1 |
| m03 | 2 | multi_hop | B | 0.96 | 0.93 | 1.00 | 34,844 | 1,439 | 3 | mcp__memex__impact_of x1, mcp__memex__list_codebases x1 |
| m03 | 3 | multi_hop | B | 0.96 | 0.93 | 1.00 | 34,840 | 1,543 | 3 | mcp__memex__impact_of x1, mcp__memex__list_codebases x1 |
| m04 | 1 | multi_hop | A | 0.93 | 0.93 | 0.93 | 77,641 | 3,418 | 13 | Grep x9, Read x3 |
| m04 | 2 | multi_hop | A | 1.00 | 1.00 | 1.00 | 47,417 | 3,056 | 8 | Grep x7 |
| m04 | 3 | multi_hop | A | 1.00 | 1.00 | 1.00 | 60,133 | 3,126 | 10 | Grep x7, Read x2 |
| m04 | 1 | multi_hop | B | 1.00 | 1.00 | 1.00 | 47,233 | 1,917 | 7 | Read x2, mcp__memex__find_symbol x1, mcp__memex__impact_of x1, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |
| m04 | 2 | multi_hop | B | 1.00 | 1.00 | 1.00 | 77,299 | 2,588 | 9 | Read x4, mcp__memex__callees x1, mcp__memex__find_symbol x1, mcp__memex__impact_of x1, mcp__memex__list_codebases x1 |
| m04 | 3 | multi_hop | B | 1.00 | 1.00 | 1.00 | 109,619 | 3,294 | 14 | Read x9, mcp__memex__find_symbol x1, mcp__memex__impact_of x1, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |
| m05 | 1 | multi_hop | A | 1.00 | 1.00 | 1.00 | 52,694 | 2,646 | 6 | Grep x3, Read x2 |
| m05 | 2 | multi_hop | A | 1.00 | 1.00 | 1.00 | 120,456 | 3,732 | 11 | Grep x7, Read x3 |
| m05 | 3 | multi_hop | A | 1.00 | 1.00 | 1.00 | 89,053 | 3,236 | 9 | Grep x4, Read x4 |
| m05 | 1 | multi_hop | B | 1.00 | 1.00 | 1.00 | 31,973 | 1,209 | 4 | mcp__memex__callers x2, mcp__memex__list_codebases x1 |
| m05 | 2 | multi_hop | B | 1.00 | 1.00 | 1.00 | 22,015 | 1,072 | 3 | mcp__memex__callers x1, mcp__memex__list_codebases x1 |
| m05 | 3 | multi_hop | B | 1.00 | 1.00 | 1.00 | 22,012 | 1,093 | 3 | mcp__memex__callers x1, mcp__memex__list_codebases x1 |
| m06 | 1 | multi_hop | A | 1.00 | 1.00 | 1.00 | 84,322 | 3,695 | 14 | Grep x8, Read x5 |
| m06 | 2 | multi_hop | A | 1.00 | 1.00 | 1.00 | 106,260 | 3,849 | 15 | Grep x10, Read x4 |
| m06 | 3 | multi_hop | A | 1.00 | 1.00 | 1.00 | 122,704 | 3,728 | 15 | Grep x9, Read x5 |
| m06 | 1 | multi_hop | B | 1.00 | 1.00 | 1.00 | 31,286 | 1,330 | 5 | Read x2, mcp__memex__callers x1, mcp__memex__list_codebases x1 |
| m06 | 2 | multi_hop | B | 1.00 | 1.00 | 1.00 | 31,311 | 1,474 | 5 | Read x2, mcp__memex__callers x1, mcp__memex__list_codebases x1 |
| m06 | 3 | multi_hop | B | 1.00 | 1.00 | 1.00 | 41,686 | 1,587 | 6 | Read x2, mcp__memex__callers x2, mcp__memex__list_codebases x1 |
| m07 | 1 | multi_hop | A | 0.96 | 0.92 | 1.00 | 93,877 | 3,467 | 14 | Grep x6, Read x7 |
| m07 | 2 | multi_hop | A | 0.96 | 0.92 | 1.00 | 61,809 | 2,794 | 11 | Grep x4, Read x6 |
| m07 | 3 | multi_hop | A | 0.96 | 0.92 | 1.00 | 62,187 | 2,992 | 12 | Grep x5, Read x6 |
| m07 | 1 | multi_hop | B | 1.00 | 1.00 | 1.00 | 75,306 | 2,846 | 14 | Read x8, mcp__memex__callees x1, mcp__memex__find_symbol x1, mcp__memex__impact_of x1, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |
| m07 | 2 | multi_hop | B | 1.00 | 1.00 | 1.00 | 68,492 | 2,889 | 13 | Read x8, mcp__memex__find_symbol x1, mcp__memex__impact_of x1, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |
| m07 | 3 | multi_hop | B | 1.00 | 1.00 | 1.00 | 71,918 | 3,009 | 14 | Read x8, mcp__memex__callers x1, mcp__memex__find_symbol x1, mcp__memex__impact_of x1, mcp__memex__list_codebases x1, mcp__memex__search_docs x1 |
| m08 | 1 | multi_hop | A | 1.00 | 1.00 | 1.00 | 29,002 | 1,220 | 4 | Grep x3 |
| m08 | 2 | multi_hop | A | 1.00 | 1.00 | 1.00 | 30,057 | 1,298 | 5 | Grep x4 |
| m08 | 3 | multi_hop | A | 1.00 | 1.00 | 1.00 | 28,703 | 1,437 | 5 | Grep x4 |
| m08 | 1 | multi_hop | B | 1.00 | 1.00 | 1.00 | 22,959 | 795 | 3 | mcp__memex__impact_of x1, mcp__memex__list_codebases x1 |
| m08 | 2 | multi_hop | B | 1.00 | 1.00 | 1.00 | 22,961 | 775 | 3 | mcp__memex__impact_of x1, mcp__memex__list_codebases x1 |
| m08 | 3 | multi_hop | B | 1.00 | 1.00 | 1.00 | 22,965 | 744 | 3 | mcp__memex__impact_of x1, mcp__memex__list_codebases x1 |

## Missed and extra

### m01 B (run 1)

- missed: `mealie.routes.users.forgot_password.reset_password`

### m01 B (run 2)

- missed: `mealie.routes.users.forgot_password.reset_password`

### m01 B (run 3)

- missed: `mealie.routes.users.forgot_password.reset_password`

### m02 A (run 1)

- missed: `mealie.services.migrations.cookn.CooknMigrator._process_cookbook`
- extra: `mealie.services.migrations.cookn.CooknMigrator._migrate`

### m03 A (run 1)

- extra: `tests.integration_tests.test_spa.test_spa_serve_recipe_with_meta`
- extra: `tests.integration_tests.test_spa.test_spa_serve_recipe_with_meta_invalid_data`
- extra: `tests.unit_tests.core.test_dependencies.test_auth_token_comes_from_the_authorization_header`
- extra: `tests.unit_tests.core.test_dependencies.test_auth_token_falls_back_to_the_session_cookie`
- extra: `tests.unit_tests.core.test_dependencies.test_authorization_header_wins_over_the_cookie`
- extra: `tests.unit_tests.core.test_dependencies.test_no_credential_yields_an_empty_token`
- extra: `tests.unit_tests.core.test_dependencies.test_unrelated_cookies_are_ignored`

### m03 B (run 1)

- extra: `mealie.routes.spa.mount_spa`

### m03 B (run 2)

- extra: `mealie.routes.spa.mount_spa`

### m03 B (run 3)

- extra: `mealie.routes.spa.mount_spa`

### m04 A (run 1)

- missed: `mealie.db.models.household.cookbook.CookBook`
- extra: `mealie.db.models.household.cookbook.CookBookModel`

### m07 A (run 1)

- extra: `tests.unit_tests.services_tests.backup_v2_tests.test_backup_v2._d7c6efd2de42_migrate_favorites_and_ratings_to_user_ratings`

### m07 A (run 2)

- extra: `tests.unit_tests.services_tests.backup_v2_tests.test_backup_v2._d7c6efd2de42_migrate_favorites_and_ratings_to_user_ratings`

### m07 A (run 3)

- extra: `tests.unit_tests.services_tests.backup_v2_tests.test_backup_v2._d7c6efd2de42_migrate_favorites_and_ratings_to_user_ratings`
