# PrivateFind backend

FastAPI (async) · SQLAlchemy 2 · MySQL 8 · Python 3.13. Design: [architecture](../docs/design/architecture.md), [API contract](../docs/design/api-contract.md).

## Run locally
Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
docker compose up -d mysql                  # from the repo root
cd backend
cp .env.example .env                        # then edit SECRET_KEY
uv sync
uv run alembic upgrade head                 # create tables
uv run python -m scripts.seed --admin-email admin@privatefind.local --admin-password changeme123
uv run uvicorn app.main:app --reload
```

The interactive API docs are at http://localhost:8000/docs.

## Tests and lint
```bash
uv run pytest        # in-memory SQLite + mock AI: no MySQL or API key needed
uv run ruff check .
uv run ruff format .
```

## Layout
```
app/
  core/       config, async DB session, error shape
  shared/     audit log, private photo storage, rate limits, vocabularies, ai/ (mock + Claude)
  modules/    one folder per domain: router.py, service.py, models.py, schemas.py, policy.py
    identity/  locker/  found_items/  lost_reports/  matching/  claims/
migrations/   Alembic
scripts/      seed.py
tests/
```

Rules:
- Use domain services for workflows; ORM relationships follow Simon's shared database schema.
- Business rules live in `policy.py` as pure functions with unit tests.

## Schema changes
After changing a model:

```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

Review the generated file before committing it.

## Real AI
Set `AI_PROVIDER=claude` and `ANTHROPIC_API_KEY` in `.env`. If the AI is down, extraction is retried 3 times. After that, the item shows up under `GET /api/admin/items?ai_status=FAILED`, where an admin can retry or correct it.

## Team integration (2026-11-10)

The database baseline is Simon's 13-table migration `c37e42452449`, followed by the
additive backend revision `c3c3ff57c7f3`. Keep the existing asynchronous services.
See [integration notes](../docs/design/team-integration.md) for fresh and existing team DB setup.

The ESP32 API now uses Raphael's `{device_id, code}` / `{authorized, compartment, action}`
contract. State reporting uses `{device_id, occupied}` / `{compartment, state}`.
The seed defaults to device `locker_01`, locker code `L1`, and one physical compartment.
All stored lifecycle/status values now use Simon's lowercase vocabulary.
