# PrivateFind backend

FastAPI (async) · SQLAlchemy 2 · MySQL 8 · Python 3.13. Design: [architecture](../docs/design/architecture.md), [API contract](../docs/design/api-contract.md).

## Run everything with Docker

Only Docker Desktop is needed on the host. From the repository root:

```bash
docker compose up --build
```

Compose waits for MySQL, then the backend applies migrations, seeds an admin and
one-compartment locker, and starts on port 8000. Open http://localhost:8000/docs.
The app currently provides an API interface; there is no merged frontend yet.

Defaults: `AI_PROVIDER=mock`, admin `admin@example.com` / `changeme123`, locker `L1`,
device `locker_01`. With mock AI, use a finder note such as
`Black Samsung phone, cat sticker, serial ends 4821` for the test flow.

The seed is safe to run repeatedly and keeps the existing device key. Save the key
printed on the **first** startup for the ESP32. View logs with:

```bash
docker compose logs backend
```

Database data and photos are kept in `mysql-data` and `photo-data` volumes.
`docker compose down` stops the app and retains both volumes. Start in the
background with `docker compose up --build -d`; inspect health with `docker compose ps`.

Optional environment variables can be set in a root `.env` file or the shell:
`SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `PORT` (host port), `AI_PROVIDER`,
`ANTHROPIC_API_KEY`, and `CLAUDE_MODEL`. No `.env` file is required for the demo.
Changing admin defaults after the database is seeded does not reset an existing
account's password. Container database/storage paths are configured by Compose;
the local `backend/.env` is excluded from the image.

To connect the physical ESP32, use the laptop's LAN IP and published port in its
backend URLs, and the saved device key. The firmware runs on the ESP32 itself.

## Run the backend locally
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

For frontend integration, see the [complete API guide](../docs/api/frontend-integration.md),
[OpenAPI snapshot](../docs/api/openapi.json), and [Postman collection](../docs/api/postman-collection.json).
Regenerate the JSON exports from this directory with `uv run python -m scripts.export_api_docs`.

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
