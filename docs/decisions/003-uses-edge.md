# ADR-003: USES, an edge for code named as a value

- Status: accepted
- Date: 2026-11-05 (Phase 9)

## Context

`impact_of` walks CALLS, INHERITS, REFERENCES and IMPORTS. The hand-verified check in `eval/impact_check.md` found that a large share of real dependents reach a symbol without calling it:

- a function passed as a value: `Depends(get_current_user)` in a parameter default or a class attribute, `add_task(service.scrape)`;
- a class used as a value: `select(Tool)`, `Tool.id == x`, `isinstance(x, Tool)`, `Model.model_validate(...)`;
- a class constructed when it has no `__init__` in the codebase (ORM models, Pydantic schemas), which gives no CALLS edge by DESIGN section 9.

On Mealie, 5 of the 6 direct dependents of `get_current_user` and 12 of the 25 of the `Tool` model were missing for this reason. A FastAPI dependency's dependents are the widest set in such an app, and Memex showed none of them.

Recording these as CALLS would be wrong: `callers` would then list code that never calls the symbol, and the `exact`/`inferred` labels describe call sites. The schema (`graph/model.py`) and the tool contract (`query/models.py`) are frozen by ADR-001, so a new edge type needs this record.

## Decision

Add one edge type, `USES`, from a Function or Class to a Function or Class, with a `line` and no other property.

- **What counts:** a name or dotted name, read (not assigned), whose longest leading part that resolves names a codebase Function or Class. Names resolve as for calls (DESIGN section 9): a definition or import in the module, an import inside the function, a module alias (`tools.helper`), and `self.m` or `self.a.m` through the class or its typed attributes (rule 3). Never by a unique name: there is no `inferred` USES.
- **What does not count:**
  - a call that gives a CALLS edge (`helper()`, `C.m()`, `C()` with an `__init__`);
  - type annotations (parameters, returns, `x: C = ...`), string constants, decorators;
  - a name bound locally (a parameter, variable or nested def), a builtin, or a name from outside the codebase;
  - a symbol naming itself;
  - a pair the codebase's extractors already link by REFERENCES (`relationship(User)` stays REFERENCES only).
- **Where it is read:**
  - a function's body (nested defs and lambdas included, as for calls) and its own parameter defaults;
  - a class body's statements other than nested defs and classes (assigned values, not annotations), with the class as the source.
- **One edge per pair:** the first line.
- **In the tools:** `impact_of` and `check_change` (since removed by ADR-004) walk USES like CALLS: a dependent reached by USES is expanded. `callers` and `callees` do not use it; they stay about calls. `PathStep.edge` gains the value `USES`.

## Consequences

- `impact_of get_current_user` reaches every route that depends on it, and the controllers that inherit it. Classes constructed or used as values (schemas, models) gain the functions that use them.
- More edges and larger impact sets. Precision rests on name resolution being exact; a dependent found by USES is real code that names the symbol, but naming is not always depending on behaviour (an `isinstance` check against a class whose fields change is unaffected). The `impact_check.md` re-run measures this.
- Still missed: a value reached through a local variable (`scraper = Scraper(); add_task(scraper.scrape)`), class bases' type arguments (`Repo[Out, Tool]`), and module-level code, which has no Function or Class to start from.
- `graph/model.py` (`EdgeKind`) and `query/models.py` (`ImpactEdge`) each gain `"USES"`; the contract snapshot is regenerated. No other field changes.
