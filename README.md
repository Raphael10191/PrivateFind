# PrivateFind

AI-assisted campus lost and found with private ownership verification and a smart locker.
Software Engineering project, Sejong University (Team Roaster).

## Setup (local, without Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then enter your MySQL data and a SECRET_KEY
alembic upgrade head               # creates all 13 tables
python -m backend.database.seed --demo   # locker with 1 compartment, test users, demo items
uvicorn backend.main:app --reload --host 0.0.0.0
```

API documentation with "Try it out": http://localhost:8000/docs

Run the tests (they use a temporary SQLite database, no MySQL needed):

```bash
pytest
```

## Test data (seed, only for development)

| What | Value |
|---|---|
| Locker | `device_id = locker_01`, device key = `DEVICE_KEY` from `.env` (default `dev-locker-key`) |
| Compartments | only compartment 1 (prototype with one compartment) |
| Admin | `admin` / `admin1234` |
| Owner | `testowner` / `owner1234` |
| `--demo` | black Adidas wallet + blue umbrella, lost report of `testowner` for a wallet |

## Project structure

```
backend/
  main.py              FastAPI app, includes the routers
  config.py            settings from .env (upload folder, code expiry, match weights)
  security.py          hashing of passwords (Argon2), codes (HMAC) and tokens
  database/            SQLAlchemy models, connection, seed script
  services/            business logic, the only place that uses the database
    deposits.py        finder deposit, photos, finder answers, AI attributes   (6.3)
    locker.py          one-time codes, compartment states                      (6.7)
    lost_reports.py    lost-item report                                        (6.4)
    matching.py        Match Score and top 3 candidates                         (6.6)
    embeddings.py      semantic similarity, mock until the embedding API works  (7.2)
    users.py           create user, password check                             (6.1)
    attempts.py        growing wait times and alerts after failed claims       (8.3)
    audit.py           audit log                                               (9.2)
  api/                 REST routes (small, they call the services)
    deps.py            logged-in user, admin check, IP rate limit
alembic/               database migrations
iot/                   ESP32 firmware
tests/                 pytest
```

## REST API

| Endpoint | Used by | Purpose |
|---|---|---|
| `POST /api/deposit-sessions` | Finder (QR page) | `{"locker_id": 1}` -> token. 409 if no compartment is free |
| `POST /api/deposits` | Finder | Multipart: `token`, `location`, `category`, `note`, `answers` (JSON), 3 × `photos` -> compartment + deposit code |
| `POST /api/lost-reports` | Owner | Create a lost-item report |
| `GET /api/lost-reports` | Owner | Own reports |
| `GET /api/lost-reports/{id}/candidates` | Owner | Top 3 candidates (score >= 60), public data only |
| `POST /api/device/codes/validate` | ESP32 | `{"device_id": "locker_01", "code": "123456"}` + header `X-Device-Key` -> `{"authorized": true, "compartment": 1, "action": "deposit"}` |
| `POST /api/device/compartments/{no}/state` | ESP32 | `{"device_id": "locker_01", "occupied": true}` after the door is closed and # is pressed |
| `GET /api/admin/audit-log` | Admin | Newest log entries, `?only_alerts=true` for the activity alerts. Only role admin |

Allowed categories (dropdown in the frontend): see `CATEGORIES` in `backend/config.py`.

## Security (Week 10)

| Topic | How | Where |
|---|---|---|
| Passwords | Argon2 hash, never plain text | `security.py` |
| Codes, tokens, device key | only hashes (HMAC / SHA-256), codes are one-time and expire | `security.py`, `services/locker.py` |
| Authentication | `get_current_user` (until login is ready: header `X-User-Id`) | `api/deps.py` |
| Authorization | admin routes need role admin (403), owners only see their own reports | `api/deps.py`, `services/lost_reports.py` |
| ESP32 | every request needs `X-Device-Key` | `api/device.py` |
| Input validation | Pydantic (types, lengths), fixed category list, 3 photos, max. 10 MB, file must really be an image | `api/*.py`, `services/deposits.py` |
| SQL injection | only SQLAlchemy ORM, values are sent as parameters, no SQL strings | all services, `tests/test_security.py` |
| Private data | photos in a private folder, private attributes never in the candidate answer | `services/matching.py` |
| Rate limit | max. 30 requests per IP and minute (HTTP 429), never a full IP block | `api/deps.py` |
| Failed claims | growing wait times per account and item (5, 10, 20, 60 min) | `services/attempts.py` |
| Activity alerts | many failed claims on one item / many wrong keypad codes -> `alert_...` in the audit log | `services/attempts.py`, `services/locker.py` |

Owner routes need the logged-in user. Until login (6.1) is ready, send the header
`X-User-Id: <user_id>` (see `backend/api/deps.py`, only `get_current_user` has to be replaced).

## Notes for the team

- **AI (Zohidjon):** after the deposit, `item.ai_status` is `pending`. Read the photos with
  `deposits.get_photo_paths(item)` and store the result with `deposits.save_ai_attributes(db, item_id, AiResult(...))`
  or `deposits.mark_ai_failed(...)`.
- **Ownership verification (Zohidjon):** before a claim use `attempts.claim_wait_until(db, user_id, item_id)`;
  after approval `locker.create_pickup_code(db, claim)` returns the pickup code for the owner;
  after a rejection call `attempts.alert_if_many_failed_claims(db, item_id)`.
  Add `dependencies=[Depends(limit_by_ip)]` to the claim router (IP limit).
- **Login (Zohidjon):** only replace `get_current_user` in `backend/api/deps.py`. `users.authenticate()` checks
  username and password. The admin check `get_current_admin` then works automatically.
- **Embeddings (Zohidjon):** replace `get_embedding()` in `services/embeddings.py` with the API call,
  then set `SEMANTIC_ENABLED=true` in `.env`.
- **Locker (Raphael):** new URL `/api/device/codes/validate`, same JSON as now plus the header `X-Device-Key`.
  After the door is closed, send the sensor value to `/api/device/compartments/{no}/state`.
  The old test route `/locker/validate` (accepted "1234") is removed.
- **Frontend (Muslimbek):** all forms and answers are described at `/docs`. Categories as a dropdown
  from `CATEGORIES`. Error texts come in `detail` and can be shown directly (400, 409, 429).
- Photos lie in `UPLOAD_DIR` (default `uploads/`). This folder is private and never served as static files.
- Times are local server time. In Docker set `TZ=Asia/Seoul` for the backend and the MySQL container.
