# Agent Guide

Start with `create_app()` in app/main.py.

## Layers

- Routes in `app/routes/` call services, never repos directly.
- Services inherit from `BaseService` and get repositories from `AllRepositories`.
- Never call `get_one` on a repository from a route.
- Do not use `get` or `__init__` as an example; `dict` is not ours.

## Database

Models live in app/db/models/ and inherit from app.db.models._model_base.SqlAlchemyBase.
Never edit app/migrations/ by hand; app.db.models.missing.Thing does not exist.
Files matching app/repos/repository_*.py hold one repository each.
