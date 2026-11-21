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

## Local simulated reporting sandbox

This opt-in backend development mode is separate from the frontend redesign.
It enables only lost-report creation and the existing cached candidate reads
(`refresh=false`). The mock provider compares text; it does not verify photos.
No matching rules, ownership rules, models, migrations, or firmware are changed.

All four settings are required:

```dotenv
APP_ENV=development
ALLOW_MOCK_AI_REPORTS=true
AI_PROVIDER=mock
DATABASE_URL=sqlite+aiosqlite:///:memory:
```

The application rejects production/test environments, real AI providers, MySQL,
and file-backed/shared databases when the flag is enabled. Startup creates the
existing tables in a fresh in-memory database. Test accounts and reports last
only for that backend process; nothing is copied from the normal MySQL database.
Use one backend process, without `--reload` or multiple workers. Do not run seed,
demo-seed, or migration commands for this sandbox.

The sandbox uses the separate `privatefind_mock_session` cookie. Registration
and login still use the normal authentication implementation. Create a new test
Owner through the existing registration page; normal accounts are not imported.

From `backend/`, with the existing Python 3.13 development dependencies installed:

```powershell
$env:APP_ENV = 'development'
$env:ALLOW_MOCK_AI_REPORTS = 'true'
$env:AI_PROVIDER = 'mock'
$env:DATABASE_URL = 'sqlite+aiosqlite:///:memory:'
$env:SECRET_KEY = [guid]::NewGuid().ToString('N')
uv run --locked --group dev uvicorn app.main:app --host 127.0.0.1 --port 8002
```

If using an existing development virtual environment, replace `uv run --locked
--group dev uvicorn` with `python -m uvicorn`. `aiosqlite` is already a declared
development dependency; Docker's production image intentionally omits it.
Docker Compose and its normal containers/volumes do not need changes or restarts.

On the Windows workspace where native Python extensions are blocked by Application
Control, use the existing Linux backend image and the isolated pure-Python test
tools prepared for this change. From the repository root in PowerShell:

```powershell
$pfRepo = (Get-Location).Path
$pfDocker = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
$pfTools = Join-Path $env:TEMP 'privatefind-mock-reporting-testdeps'
$pfSecret = [guid]::NewGuid().ToString('N')
& $pfDocker run --rm --name privatefind-local-mock `
  -p 127.0.0.1:8002:8000 `
  --mount "type=bind,source=$pfRepo\backend\app,target=/sandbox/app,readonly" `
  --mount "type=bind,source=$pfTools,target=/testdeps,readonly" `
  --env PYTHONPATH=/sandbox:/testdeps `
  --env APP_ENV=development --env ALLOW_MOCK_AI_REPORTS=true `
  --env AI_PROVIDER=mock --env 'DATABASE_URL=sqlite+aiosqlite:///:memory:' `
  --env "SECRET_KEY=$pfSecret" --workdir /sandbox --entrypoint python `
  privatefind-backend -B -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

This starts a separate sandbox using the existing image: no rebuild, production
container restart, MySQL network, database volume, photo volume, secret file, or
device configuration is mounted. Only the host loopback port is published. The
temporary tools directory supplies the already-declared `aiosqlite` development
dependency; a future machine can instead use the standard Python/uv setup above.

In a **second PowerShell window**, from the repository root:

```powershell
$env:BACKEND_URL = 'http://127.0.0.1:8002'
$env:FRONTEND_PORT = '8003'
.\frontend\.venv\Scripts\python.exe -B .\frontend\preview.py
```

Open `http://127.0.0.1:8003/register`, create a test Owner, and report a lost item.
The existing availability banner must say **Local development · Simulated
matching** on all screens, including read-only report/results pages. A fresh
database has no found items, so showing no candidates is expected. Positive
matching fixtures exist only in automated tests; no locker acknowledgement is
fabricated in the running application.

The server refuses all other operations in this mode, including claims, photo
verification, Finder deposits, pickup codes, admin operations, device validation,
state updates, heartbeats, and the legacy `/locker/validate` alias. Reporting
uses only the deterministic mock provider and database audit records; no external
notification integration is called. The real-provider readiness gate remains
unavailable for mock AI even when reporting is enabled.

### Return to protected configuration

Stop both sandbox processes with Ctrl+C and close the sandbox browser tab. The
in-memory accounts, reports, and rankings disappear with the backend process;
normal MySQL and photo volumes remain untouched. Close those PowerShell windows
to discard their process-scoped environment settings, then return to the normal
frontend/backend URLs and configuration. Defaults remain `APP_ENV=production`
and `ALLOW_MOCK_AI_REPORTS=false`. If reusing a shell instead, remove its sandbox
settings before restoring the normal configuration:

```powershell
Remove-Item Env:APP_ENV, Env:ALLOW_MOCK_AI_REPORTS, Env:AI_PROVIDER, Env:DATABASE_URL, Env:SECRET_KEY -ErrorAction SilentlyContinue
# In the frontend shell:
Remove-Item Env:BACKEND_URL, Env:FRONTEND_PORT -ErrorAction SilentlyContinue
```

Mock AI without the explicit sandbox configuration continues to block reports.
Normal reporting/ownership flows require the configured Qwen/Claude provider to
pass its existing readiness checks. Do not copy sandbox records into normal data.

### Focused checks

```bash
uv run --locked --group dev pytest -p no:cacheprovider tests/test_ai_readiness.py
uv run --locked --group dev ruff check app/core/config.py app/shared/ai/readiness.py app/main.py app/modules/lost_reports/router.py app/modules/matching/router.py tests/conftest.py tests/test_ai_readiness.py
```

From the repository root, using Node 18+ and no additional JavaScript packages:

```bash
node frontend/tests/mock_reporting.test.cjs
```

## Normal demo data (outside the reporting sandbox)

For the existing normal demo environment only, seed a separate virtual locker
with five items from the repository root. Do not run this for the reporting sandbox:

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
