# PrivateFind

AI-assisted campus lost-and-found system with private ownership verification and smart-locker handover.
Sejong University · Software Engineering · Team **Roaster**.

| Member | Role |
|---|---|
| Zohidjon Mahmudjonov | Team Leader · AI & Backend |
| Umarov Muslimbek | UI & Frontend |
| Gerthofer Simon | Database & Matching |
| Falk Raphael | IoT & Locker |

## Start PrivateFind

Install Docker Desktop and Python 3.13. From the repository root, open or create
`.env` and configure Qwen. Keep your existing `SECRET_KEY` if you already have
users or locker codes.

```dotenv
SECRET_KEY=replace-with-a-long-random-value
AI_PROVIDER=qwen
QWEN_BASE_URL=https://your-qwen-host.example/v1
QWEN_API_KEY=replace-with-your-api-key
QWEN_MODEL=
```

An empty model name lets the backend discover it through Qwen's `/models`
endpoint. Keep `.env` private. The full list of AI settings is in
[`backend/.env.example`](backend/.env.example).

```bash
docker compose up -d --build backend
python3 -m venv frontend/.venv
frontend/.venv/bin/python -m pip install -r frontend/requirements.txt
frontend/.venv/bin/python frontend/preview.py
```

- [Finder · Locker L1](http://localhost:8001/found/new?locker=L1)
- [Owner · Sign in or register](http://localhost:8001/login)
- [Operator · Claim reviews](http://localhost:8001/admin/claims)
- [Backend · API docs](http://localhost:8000/docs)

For a phone on the same network, start the frontend with
`FRONTEND_HOST=0.0.0.0 frontend/.venv/bin/python frontend/preview.py`.
Replace `localhost` in the frontend links with your computer's LAN address.
Set `FRONTEND_PORT` if you already use another port, or `BACKEND_URL` if
the backend runs on a different address.

Compose starts MySQL, runs migrations and seeds the operator account and locker
`L1`. On a fresh database the default operator login is `admin@example.com` /
`changeme123`. Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` before first startup
if others can reach the app. `docker compose down` stops the backend and
retains the database and photos.

## How it works

1. The finder opens the locker QR link, uploads photos and confirms the deposit.
   Qwen extracts visible details. The backend issues the deposit code.
2. The owner submits a loss report. Matching ranks plausible finds and exposes
   only the public candidate fields.
3. The backend checks ownership evidence against the found item. It issues a
   pickup code for approved claims or shows the next step for unresolved claims.
   An authorized operator can review claims and manage the locker.
4. The ESP32 validates codes with the backend and reports compartment occupancy
   after the deposit or pickup.

For the ESP32, copy `iot/locker_mvp/secrets.example.h` to `secrets.h` in the same
folder and enter the Wi-Fi settings, your computer's LAN address and the device
key printed in `docker compose logs backend` on the first startup. The default
device is `locker_01`. See the [firmware contract](docs/design/team-integration.md#firmware-contract).

## Project layout

| Directory | Purpose |
|---|---|
| `frontend/` | Jinja templates, shared CSS/JS and a server that forwards API requests |
| `backend/app/modules/` | Finder, reports, matching, claims, identity and lockers |
| `backend/app/shared/ai/` | Image analysis, text comparison, photo verification and AI availability |
| `backend/migrations/` | Versioned database schema |
| `backend/tests/` | API, policy and integration tests |
| `iot/locker_mvp/` | ESP32 firmware and configuration template |

Run the test suite with `cd backend && uv run --locked pytest`. Tests use
temporary data and simulated AI/device calls.

## Further documentation

- [Backend development and API exports](backend/README.md)
- [Architecture](docs/design/architecture.md) and [frontend API guide](docs/api/frontend-integration.md)
- [OpenAPI snapshot](docs/api/openapi.json) and [Postman collection](docs/api/postman-collection.json)
- [Project proposal](docs/PrivateFind_Project_Proposal_v2.pdf) and [task checklist](docs/TASKS.md)
