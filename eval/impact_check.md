# impact_of accuracy check on Mealie (Phase 9, slice 1)

A hand-verified check of `impact_of` on four Mealie symbols, run before any fix or paid eval. Ground truth comes from `grep` and reading the code, never from Memex. Memex was then called through the MCP tools with `limit=200` so nothing was cut. The walk is breadth first, so the depth-3 result contains the depth-1 and depth-2 results (each dependent carries its distance); one call per symbol at `max_depth=3` covers all three depths, except `Tool`, which was called at 1, 2 and 3.

Mealie `v3.30.0` (`9552df6`), indexed graph as of the Phase 7 merge (`4228df3`).

## Summary

| Symbol | Edge path tested | Depth | Found | Correct | Truth | Precision | Recall |
|---|---|---|---|---|---|---|---|
| `hash_password` | CALLS, IMPORTS | 1 to 3 | 17 | 17 | 18 | 1.00 | 0.94 |
| `get_current_user` | `Depends(...)` | 1 | 5 | 5 | 10 | 1.00 | 0.50 |
| `RecipeService.create_one` | injected attributes | 1 | 3 | 3 | 7 | 1.00 | 0.43 |
| `RecipeService.create_one` | injected attributes | 1 to 2 | 6 | 6 | 22 | 1.00 | 0.27 |
| `Tool` (ORM model) | REFERENCES, IMPORTS | 1 | 13 | 13 | 25 | 1.00 | 0.52 |
| `Tool` (ORM model) | REFERENCES, IMPORTS | 2 only | 74 | 0 | not enumerated | 0.00 | n/a |

Truth counts functions, classes and modules. Star re-exports through a package `__init__` (`from .x import *`) are left out of the truth on both sides; Memex does not list them.

**Findings, by how much they cost:**

1. **Transitive walk through a class reached by REFERENCES or IMPORTS is noise.** For `Tool`, all 74 dependents added at depth 2 come from classes that reference `Group`, `RecipeModel`, `Household` or `CookBook`, or modules that import those classes. None of them depends on `Tool`: `Category` references `Group`, which has a relationship to `Tool`, so `Category` is listed. `Tool`'s own module is listed at depth 2 because it imports `Group`. Depth 3 reaches 125. CALLS chains were sound in every case checked: when a function changes, its callers' behaviour does change.
2. **Calls through typed attributes (the q04 gap) lose most of the depth-2 tree.** 4 of 7 direct callers of `RecipeService.create_one` are missed, and the 12 functions above them at depth 2 are lost with them. All four attribute types are statically known:
   - `self.service`, a `cached_property` with return annotation `-> RecipeService` on a base class (`routes/recipe/_base.py:51`): 2 callers;
   - `self.recipe_service = RecipeService(...)` in `__init__` (`services/migrations/_migration_base.py:80`): 1 caller, and 10 migrators above it;
   - `self.service = service` from an `__init__` parameter annotated `service: RecipeService` (`services/scraper/recipe_bulk_scraper.py:25`): 1 caller.
3. **Functions passed as values, not called, give no edge.** `Depends(get_current_user)` (5 of 6 direct dependents of `get_current_user`), `bg_tasks.add_task(bulk_scraper.scrape, ...)`, and an ORM class used as a value (`select(Tool)`, `Tool.id == ...`, `orm.aliased(Tool)`: 12 functions and classes for `Tool`). A FastAPI dependency's blast radius is the widest in the app (34 route files subclass `BaseUserController`, 16 use `UserAPIRouter`) and Memex shows none of it.
4. **Local variables typed by a constructor** (`f_service = PasswordResetService(session); f_service.reset_password(...)`) give no edge when the method name is shared. The DESIGN section 13 limit; 1 miss here.
5. **Docs.** AGENTS.md mentions `get_current_user` twice, in a code fence (`### Python Backend`, line 114) and as `` `Depends(get_current_user)` `` (`### What to Review`, line 177); neither links (the documented call-in-backticks limit). The docs Memex did list came from dependent modules named in generic file lists (`Key Files to Reference`, `Project Overview`), not from guidance about the symbol.

**Precision was 1.00 everywhere at depth 1, and on every CALLS chain.** The two `inferred` edges in these walks (`register_user`, and the routes calling `create_from_mealie_export` and `create_from_zip` through `self.service`) were all right: unique method names rescue part of the injected-attribute gap.

## 1. `mealie.core.security.security.hash_password`

Plain function, small enough to enumerate to depth 3.

| d | Dependent | Edge | Source | Memex |
|---|---|---|---|---|
| 1 | `repos.seed.init_users.default_user_init` | CALLS | `repos/seed/init_users.py:56` | found |
| 1 | `repos.seed.init_users.dev_users` | CALLS | `repos/seed/init_users.py:16` | found |
| 1 | `routes.admin.admin_management_users.AdminUserManagementRoutes.create_one` | CALLS (`security.hash_password`) | `routes/admin/admin_management_users.py:51` | found |
| 1 | `routes.users.crud.UserController.update_password` | CALLS | `routes/users/crud.py:52` | found |
| 1 | `scripts.change_password.main` | CALLS | `scripts/change_password.py:40` | found |
| 1 | `services.user_services.password_reset_service.PasswordResetService.reset_password` | CALLS | `services/user_services/password_reset_service.py:61` | found |
| 1 | `services.user_services.registration_service.RegistrationService._create_new_user` | CALLS | `services/user_services/registration_service.py:35` | found |
| 1 | modules `repos.seed.init_users`, `scripts.change_password`, `routes.users.crud`, `services.user_services.password_reset_service`, `services.user_services.registration_service` | IMPORTS | import lines | found (5) |
| 2 | `db.init_db.init_db` | CALLS `default_user_init` | `db/init_db.py:40` | found |
| 2 | module `db.init_db` | IMPORTS `default_user_init` | `db/init_db.py:18` | found |
| 2 | `RegistrationService.register_user` | CALLS `_create_new_user` | `registration_service.py:113` | found |
| 2 | `routes.users.forgot_password.reset_password` | CALLS `PasswordResetService.reset_password` through a local variable | `routes/users/forgot_password.py:28` | **missed** (finding 4) |
| 3 | `db.init_db.main` | CALLS `init_db` | `db/init_db.py:135` | found |
| 3 | `routes.users.registration.RegistrationController.register_new_user` | CALLS `register_user` (`inferred`, unique name) | `routes/users/registration.py:33` | found |

Not a dependent, correctly absent: `UserController.update_password` is called nowhere in code (three other `update_password` methods share the name, so no wrong `inferred` edge was made). Depth 4 (`app.py:67`, `init_db.main()`) is out of range.

## 2. `mealie.core.dependencies.dependencies.get_current_user`

| d | Dependent | How it uses the symbol | Source | Memex |
|---|---|---|---|---|
| 1 | `try_get_current_user` | call | `core/dependencies/dependencies.py:97` | found |
| 1 | `get_admin_user` | `Depends(get_current_user)` default | `dependencies.py:153` | **missed** |
| 1 | `routes.auth.auth.refresh_token` | `Depends(...)` default | `routes/auth/auth.py:392` | **missed** |
| 1 | `routes._base.routers.UserAPIRouter.__init__` | `dependencies=[Depends(get_current_user)]` | `routes/_base/routers.py:24` | **missed** |
| 1 | `routes._base.permissions.RequirePermission.__call__` | `Depends(...)` default | `routes/_base/permissions.py:63` | **missed** |
| 1 | `routes._base.base_controllers.BaseUserController` | class attribute `= Depends(...)` | `routes/_base/base_controllers.py:138` | **missed** |
| 1 | modules `routes.auth.auth`, `routes._base.routers`, `routes._base.permissions`, `routes._base.base_controllers` | IMPORTS | import lines | found (4) |
| 2 | modules `routes.spa`, `routes.validators.validators` | IMPORTS `try_get_current_user` | `routes/spa/__init__.py:17`, `routes/validators/validators.py:7` | found (2) |

Depth 2 and beyond, not enumerated: every subclass of `BaseUserController` (34 route files), every route module using `UserAPIRouter` (16) and every admin route behind `get_admin_user` (12 files). Memex lists 7 dependents in total.

## 3. `mealie.services.recipe.recipe_service.RecipeService.create_one`

| d | Dependent | Call | Source | Memex |
|---|---|---|---|---|
| 1 | `RecipeService.create_from_mealie_export` | `self.create_one` | `recipe_service.py:512` | found |
| 1 | `RecipeService.create_from_zip` | `self.create_one` | `recipe_service.py:543` | found |
| 1 | `AIRecipeService.create_from_ai` | `self.create_one` (inherited) | `services/recipe/ai_recipe_service.py:60` | found |
| 1 | `routes.recipe.recipe_crud_routes.RecipeController._finish_recipe_from_web` | `self.service.create_one` (property) | `recipe_crud_routes.py:414` | **missed** |
| 1 | `RecipeController.create_one` | `self.service.create_one` (property) | `recipe_crud_routes.py:655` | **missed** |
| 1 | `services.migrations._migration_base.BaseMigrator.import_recipes_to_database` | `self.recipe_service.create_one` (set in `__init__`) | `_migration_base.py:223` | **missed** |
| 1 | `services.scraper.recipe_bulk_scraper.RecipeBulkScraperService.scrape` | `self.service.create_one` (annotated `__init__` param) | `recipe_bulk_scraper.py:111` | **missed** |
| 2 | `RecipeController._create_recipe_from_mealie_export` | `inferred` | `recipe_crud_routes.py:399` | found |
| 2 | `RecipeController.create_recipe_from_zip` | `inferred` | `recipe_crud_routes.py:531` | found |
| 2 | `RecipeController._create_recipe_with_ai` | local `ai_service.create_from_ai` | `recipe_crud_routes.py:495` | found |
| 2 | `RecipeController._create_recipe_from_web` | `self._finish_recipe_from_web` in a nested def | `recipe_crud_routes.py:376` | **missed** (cascade) |
| 2 | `RecipeController.parse_recipe_url_bulk` | `bg_tasks.add_task(bulk_scraper.scrape, ...)` | `recipe_crud_routes.py:513` | **missed** (finding 3) |
| 2 | `_migrate` of the RecipeKeeper, PlanToEat, MyRecipeBox, CopyMeThat, Paprika, Nextcloud, Chowdown, MealieAlpha and Tandoor migrators; `CooknMigrator._process_cookbook` | `self.import_recipes_to_database` | `services/migrations/*.py` | **missed** (cascade, 10) |
| 3 | `_create_recipe_from_html_or_json`, `create_recipe_from_image`, `create_recipe_with_ai`, `create_recipe_with_ai_stream` | | `recipe_crud_routes.py` | found (4) |
| 3 | `parse_recipe_url`, `parse_recipe_url_stream`, the migrator entry points | | | **missed** (cascade; not fully enumerated) |

Memex lists 10 dependents in total, all correct.

## 4. `mealie.db.models.recipe.tool.Tool`

The `tools` table has three ForeignKeys, all in module-level association tables (`tool.py:21,29,37`), which give no edge (DESIGN section 13); the relationships cover them.

| d | Dependent | How | Memex |
|---|---|---|---|
| 1 | `Group`, `RecipeModel`, `Household`, `CookBook` | `relationship("Tool")` / `relationship(Tool)` | found (4, REFERENCES) |
| 1 | modules `db.models.group.group`, `db.models.recipe.recipe`, `db.models.household.household` (under `TYPE_CHECKING`), `db.models.household.cookbook`, `repos.repository_factory`, `repos.repository_recipes`, `repos._recipe_suggestions`, `repos.repository_household`, `schema.recipe.recipe_tool` | IMPORTS | found (9) |
| 1 | `repos.repository_factory.RepositoryTools` (generic base `[..., Tool]`), `RepositoryTools._query`, `RepositoryTools.get_empty`, `AllRepositories.tools` | `Tool` as a value | **missed** (4) |
| 1 | `repos.repository_recipes.RepositoryRecipes._resolve_organizer` (annotation only), `.update`, `.page_all`, `._build_recipe_filter` | `Tool` as a value | **missed** (4) |
| 1 | `repos._recipe_suggestions.RecipeSuggestionMixin.find_suggested_recipes`, `repos.repository_household.RepositoryHousehold.statistics` | `Tool` as a value | **missed** (2) |
| 1 | `schema.recipe.recipe_tool.RecipeToolOut.loader_options`, `RecipeToolResponse.loader_options` | `selectinload(Tool.recipes)` | **missed** (2) |
| 2 | 74 more: every model with a relationship to `Group`, `RecipeModel` or `Household`, and modules importing those classes or `CookBook` | REFERENCES or IMPORTS of an intermediate class | listed, none correct (finding 1) |

## Reusable as eval questions

Each section's table is a hand-verified answer set. Candidates for a multi-hop impact eval:
- "What breaks if `hash_password` changes?" (depth 3, 12 functions): a control where Memex should be near perfect.
- "What runs `RecipeService.create_one`, directly or indirectly?" (depth 2): currently 6 of 22.
- "Which code uses `get_current_user`?" (depth 1, 6 symbols): currently 1 of 6.
- "What code would a change to the `Tool` model's columns affect?" (depth 1): currently 4 of 16 classes and functions.
