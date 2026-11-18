# PrivateFind backend

The [main README](../README.md) covers the Docker, frontend, Qwen and ESP32
setup. Use the steps below when working directly on the FastAPI backend.

## Run locally

Start Docker and install [uv](https://docs.astral.sh/uv/). Run from the
repository root:

```bash
docker compose up -d mysql
cd backend
cp -n .env.example .env
uv sync --locked
uv run alembic upgrade head
uv run python -m scripts.seed --admin-email admin@privatefind.local --admin-password changeme123
uv run uvicorn app.main:app --reload
```

Edit `backend/.env` for this local setup. Configure a real AI provider for
AI-dependent submissions in the browser. The mock provider is used by the
automated suite. `GET /api/ai/status` reports availability. Failed extraction
can be retried from the operator's found-items page. The interactive API docs
are at [localhost:8000/docs](http://localhost:8000/docs).

To seed a separate virtual locker with five items for a demo, run from the
repository root:

```bash
docker compose exec -T backend python -m scripts.demo_seed
```

## Code and tests

Each domain folder in `app/modules/` contains its API routes, data models and
workflow. Matching, claims and locker policies keep their decision rules
separate from database writes. Configuration and database sessions live in
`app/core/`. The domains share AI, photo storage, auditing and rate limiting
through `app/shared/`.

From `backend/`:

```bash
uv run --locked pytest
uv run --locked ruff check .
```

Tests use temporary SQLite databases and cover the API, AI contracts and ESP32
requests. The [team integration notes](../docs/design/team-integration.md)
describe the MySQL migration chain and device payloads.

When a database model changes, create and review a migration with
`uv run alembic revision --autogenerate -m "describe change"`. Apply it with
`uv run alembic upgrade head`.

When an API contract changes, update the
[frontend integration guide](../docs/api/frontend-integration.md) and use
`uv run python -m scripts.export_api_docs` to regenerate the checked-in exports.
