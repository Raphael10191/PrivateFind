# PrivateFind — System Architecture (v1)

> **Implementation update (2026-11-10):** We now adopt Simon's 13-table database baseline and Raphael's device contract. Lifecycle values are lowercase. Claims link through `match_id`; items retain compartment history. Your async domain services and browser payload names remain. The seed creates one compartment. See [team-integration.md](team-integration.md) and the updated [API contract](api-contract.md). The original design below records earlier decisions and is superseded where these integration notes differ.


WBS 4.1 · Owner: Zohidjon · Reviewers: Raphael (locker), Simon (data), Muslimbek (UI)
Status: **draft for team review** (target: M3 Design approved, Week 5)

---

## 1. Principles

1. **One FastAPI application**, split into **domain modules** (modular monolith). No microservices.
2. **Async end to end**: async FastAPI routes, async SQLAlchemy 2 (`asyncmy` driver), async HTTP client for the AI provider.
3. **Business rules live in plain Python** (`policy.py` files) with no FastAPI, DB or AI imports, so they are unit-testable with pytest.
4. **The fixed boundaries from the proposal stay**:
   - the browser and the ESP32 talk only to FastAPI;
   - only FastAPI touches MySQL;
   - only the backend calls the AI provider;
   - AI never approves a claim or opens a compartment.
5. **v1 is deliberately simple.** Anything marked *(v2)* is a known upgrade path, not v1 scope.

---

## 2. Big picture

```
 Finder (no account)      Owner / Admin (account)          ESP32 locker
   scans QR on locker        browser                        keypad · LCD · IR · servos
        │                        │                                │
        │  HTML+JS → JSON /api/* │                                │ JSON + X-Device-Key
        ▼                        ▼                                ▼
┌──────────────────────────── FastAPI app ─────────────────────────────────┐
│  modules/                                                                │
│   identity   found_items   lost_reports   matching   claims   locker     │
│  ─────────────────────────────────────────────────────────────────────  │
│  shared/   audit · ai (adapter: Mock | Real) · storage (private photos)  │
│  core/     config · db (async session) · security · errors               │
└──────────────┬───────────────────────────────────────┬───────────────────┘
               ▼                                       ▼
         MySQL 8 (SQLAlchemy + Alembic)         Hosted AI provider (one API key)
```

---

## 3. Domain modules

Seven proposal services → **six domain modules + shared helpers**.

| Module | Responsibility | Proposal service(s) | Owner |
|---|---|---|---|
| `identity` | Register (any email), login/logout, roles `owner` / `admin`, session cookie | — (Authentication) | Zohidjon |
| `found_items` | QR finder form, photos, optional finder contact, AI extraction trigger, item status | DepositService | Zohidjon + Muslimbek |
| `lost_reports` | Owner's lost-item report | LostReportService | Simon + Muslimbek |
| `matching` | Hybrid Match Score, top-3 candidates (pure scoring in `policy.py`) | MatchingEngine | Simon |
| `claims` | Claim submission, **Ownership Verification policy**, reservation, admin review | ClaimService + VerificationEngine | Zohidjon |
| `locker` | Compartments, deposit/pickup **code lifecycle**, device REST API | CodeService | Raphael + Zohidjon |
| `shared/audit` | `await audit.log(actor, action, entity, details)`: one function, not a module | Audit | Simon |
| `shared/ai` | `AIProvider` interface: `extract_attributes`, `compare_texts`, `MockAIProvider` for dev/tests | (AI service) | Zohidjon |

**Simplifications vs. the proposal draft:**
- **VerificationEngine is a policy inside `claims`.** It is a pure function: `evidence → (score, decision)`.
- **CodeService lives inside `locker`.** Codes exist only to open compartments.
- **Audit is a shared helper**, called by every module, rather than a service with its own API.
- **No repository layer.** Services use the SQLAlchemy `AsyncSession` directly.
- **Admin pages are part of the same app**, protected by a role check, not a separate admin app.

### Module layout (same in every module)

```
modules/<name>/
  router.py     # JSON routes under /api/<module>; thin, no business logic
  service.py    # use-cases: orchestrates DB, AI, audit; owns transactions
  models.py     # SQLAlchemy tables owned by this module
  schemas.py    # Pydantic request/response models
  policy.py     # pure business rules (only where needed: matching, claims, locker)
```

**Module rule:** a module may call another module's **`service.py`** but never import its `models.py` or touch its tables directly. This keeps the boundaries clean without extra machinery.

---

## 4. Users & access (v1)

| Actor | Account? | Can do |
|---|---|---|
| Finder | **No** | Open QR link → fill found-item form → get deposit code. May leave **optional contact** (email/phone). |
| Owner | **Yes**, any email + password (Argon2) | Lost report → candidates → claim → pickup code |
| Admin | Yes, created by seed script | Review claims, correct AI attributes, see finder contact, see audit log |

- **Sessions:** signed session cookie (Starlette `SessionMiddleware`); no JWT.
- **Finder contact privacy:** never shown to owners; visible to admins only.
- **The finder form is public, so it is protected by:**
  - a rate limit per IP/locker;
  - max 3 photos with size and type limits;
  - a valid `locker_id` required in the URL.
- *(v2)* email verification and a university-domain check.
- Note: the submitted SRS (FR3, revised proposal §4.6) still says "university e-mail". It must be updated to "any e-mail" in the next proposal revision.

### API style (D10)
- **Every feature is a JSON endpoint** under `/api/...`: the endpoint list in the revised proposal (§9.5) is the starting contract (WBS 4.2).
- **The browser pages** are static-ish HTML shells (Bootstrap) that call the API with `fetch`. Muslimbek owns the pages and JS; the backend team owns the endpoints. Pydantic `schemas.py` define the contract, and FastAPI's `/docs` page shows it.
- **Auth for the browser** stays a session cookie (same origin, `HttpOnly`, `SameSite=Lax`), so the JS needs no token handling.
- **Errors** come back in one shape: `{error: {code, message}}`.

---

## 5. Lifecycles

```
FoundItem:  SUBMITTED → STORED → RESERVED → RETURNED
                │                     (also: DEPOSIT_EXPIRED, UNCLAIMED)
                └─ ai_status: PENDING → DONE | FAILED   (independent of item status)

Claim:      SUBMITTED → APPROVED | IN_REVIEW | REJECTED
            IN_REVIEW → APPROVED | REJECTED  (admin)

LockerCode: ACTIVE → USED | EXPIRED       (purpose = DEPOSIT | PICKUP, one compartment)

Compartment: six states, as in the state diagram of the revised proposal (§9.3).
             There is no door sensor: "door closed" = user presses # on the keypad,
             then the IR sensor reports whether an item is inside.
```

**Database:** the ER design in the revised proposal (§9.4, 13 tables, Simon) is the source of truth. In particular:
- `item_attribute.visibility` marks each attribute public or private;
- `match_candidate` stores the five partial scores plus the total;
- `deposit_session` (finder token) is **not built in v1**: the QR page posts straight to `/api/deposits`, with an IP rate limit instead. The v1 schema has 12 tables.

**Reservation (no double-claim):**
- Approving a claim runs, in the same transaction: `UPDATE found_item SET status='RESERVED' WHERE id=:id AND status='STORED'`.
- If 0 rows are updated, someone else already won: the claim is not approved.

---

## 6. Key flows

### 6.1 Finder deposit (QR → form → locker)
1. QR on the locker → `GET /found/new?locker=L1` (public page).
2. The page's JS sends photos, location and note (optional contact) as multipart to `POST /api/deposits` → `found_items.service.submit()`:
   - saves the item (`SUBMITTED`, `ai_status=PENDING`) and the photos to private storage;
   - `locker.service.reserve_compartment()` returns a free compartment and a DEPOSIT code (short TTL);
   - starts AI extraction **in the background** (see §7) and **does not wait** for it.
3. The JSON response `{compartment: 2, code: "483120", expires_at}` is shown on the page: "Compartment 2 · enter the code on the keypad".
4. ESP32 → `POST /api/device/codes/validate` → `{action: "open", compartment: 2}` → the servo opens.
5. The finder closes the door and presses `#` → IR reads occupied → `POST /api/device/compartments/2/state {occupied: true}` → item becomes `STORED`.
6. If no compartment is free, the form shows "deposit unavailable" before accepting anything.

### 6.2 Owner: report → candidates → claim → pickup
1. Log in → lost report (category, time, location, brand/model, marks).
2. `matching.service.candidates(report)`:
   - filters `STORED` items by category and date;
   - computes the Match Score;
   - returns the top 3 with score ≥ 60, showing **public attributes only**.
3. The owner picks one and submits **private evidence** (serial suffix, hidden marks, contents…).
4. `claims.policy.verify(evidence, private_attributes)` gives an Ownership Score:
   - ≥ 80 and no critical conflict → approve: reserve the item and issue a PICKUP code;
   - 50–79, or a generic item → `IN_REVIEW`;
   - < 50, a critical mismatch, or > 3 failed attempts → reject + cooldown. The message never says which fact was wrong.
5. Pickup: ESP32 validates the code → opens → owner takes the item and presses `#` → IR empty → item becomes `RETURNED`, code `USED`, compartment freed.

All steps call `audit.log(...)`.

---

## 7. AI integration

### Interface (`shared/ai`)
```python
class AIProvider(Protocol):
    async def extract_attributes(self, photos: list[bytes], note: str) -> ExtractedAttributes: ...
    async def compare_texts(self, query: str, candidates: list[str]) -> list[float]: ...  # 0..1 each
```
- `MockAIProvider` returns fixed data. It is used in tests and whenever `AI_PROVIDER=mock`, so nobody is blocked without an API key.
- `extract_attributes` returns **structured JSON** (Pydantic schema). Values come from a **controlled vocabulary**, e.g. colours `black|white|blue|...`, so "navy" and "dark blue" both become `blue` at extraction time.
- Each extracted attribute has a confidence value and a visibility:
  - **public**: category, colour, brand;
  - **private**: serial fragments, stickers, damage, contents.

  They are stored as `item_attribute` rows.
- `compare_texts` serves both the 20% semantic part of the Match Score (lost description vs. ≤ N candidates in one call) and comparing claimant evidence with private attributes.

### Background job with async retry
- After the finder form is saved, `asyncio.create_task(run_extraction(item_id))` runs (via FastAPI `BackgroundTasks`).
- `run_extraction` makes 3 attempts with exponential backoff (1 s, 4 s, 16 s), each with a timeout of about 10 s.
  - On success: save the attributes and set `ai_status=DONE`.
  - On final failure: set `ai_status=FAILED`. The admin page has a **Retry** button.
- On app startup, items still `PENDING` are re-queued, because in-memory tasks are lost if the server restarts.
- The **status column on the item is the only job state**: no Celery, no Redis, no job table.
- An item enters matching only once it has a category, i.e. after AI extraction succeeds or an admin corrects it.

### Provider choice (D5, agreed)
**One provider (Claude API) for all AI calls, no embeddings.**
- **Why:**
  - Claude's Messages API handles images and returns schema-validated JSON (structured outputs).
  - We have three AI tasks: extract, compare for matching, compare evidence. All three become prompts on one endpoint behind one adapter, with one API key.
- **Trade-off:** Claude has no embeddings endpoint, so semantic similarity is an LLM-scored comparison rather than cosine similarity. That is fine at demo scale (a few items, ≤ 3–5 candidates per call). The weighted formula and thresholds stay deterministic in `matching/policy.py`.
- **Alternative:** a provider that offers both vision and embeddings (one key), with embeddings stored as a JSON column and cosine similarity in Python. This only changes `RealAIProvider`, not any module.

---

## 8. Locker device API (v1)

All requests are initiated by the ESP32; the backend never pushes to the device.

Paths follow the revised proposal (§9.5), which Raphael's firmware targets.

| Method & path | Body | Response |
|---|---|---|
| `POST /api/device/codes/validate` | `{code}` | `{action: "open", compartment: 2, message}` or `{action: "deny", message}` |
| `POST /api/device/compartments/{no}/state` | `{occupied: true \| false}` (sent after `#` is pressed) | `{ok: true, message}` |
| `POST /api/device/heartbeat` *(optional)* | `{firmware_version}` | `{ok: true, server_time}` |

- **Auth v1:** each locker has an API key. The ESP32 sends `X-Device-Key: <key>`, and the backend compares it with the key's hash in the `locker` table.
- *(v2, WBS 8.4)* HMAC signature with a timestamp, to prevent replayed requests. Only the auth dependency changes.
- Codes: 6 digits, single-use, bound to one compartment.
  - Max 5 wrong entries per minute per locker.
  - DEPOSIT TTL 15 min; PICKUP TTL 48 h (configurable).
- `message` is short enough for the 16×2 LCD.

---

## 9. Repository layout

```
private-find/
├─ backend/
│  ├─ app/
│  │  ├─ main.py                 # create_app(), include module routers, startup re-queue
│  │  ├─ core/                   # config.py (pydantic-settings), db.py, security.py, errors.py
│  │  ├─ shared/                 # audit/, ai/ (provider.py, mock.py, real.py), storage/
│  │  ├─ modules/
│  │  │  ├─ identity/  found_items/  lost_reports/  matching/  claims/  locker/
│  │  ├─ pages.py                # serves the HTML page shells (no logic)
│  │  ├─ templates/              # page shells: base.html + one per screen (Muslimbek)
│  │  └─ static/                 # css/js (fetch calls to /api/*); never photos
│  ├─ migrations/                # Alembic
│  ├─ scripts/                   # seed.py (admin + locker + device key)
│  ├─ tests/
│  │  ├─ unit/                   # policy.py tests, no DB
│  │  └─ integration/            # HTTPX + test MySQL
│  ├─ pyproject.toml             # uv, locked deps
│  └─ .env.example
├─ firmware/locker/              # ESP32 Arduino sketch (Raphael)
├─ docs/                         # TASKS.md, design/, SRS, reports
├─ docker-compose.yml            # MySQL for local dev
└─ README.md
```

**Repo hygiene:**
- `main` is protected; work happens on feature branches with PRs, and every PR gets 1 reviewer.
- Branch names follow `feat/<module>-<thing>` or `fix/...`.
- Tooling: `ruff` for lint and format, `pytest` in CI (GitHub Actions).
- Secrets live only in `.env`, which is git-ignored; `.env.example` is committed.

---

## 10. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | Modular monolith with domain modules | ✅ agreed |
| D2 | Async end to end; AI extraction as a background task with 3× retry plus a status column | ✅ agreed |
| D3 | Accounts with any email + password; finder anonymous with optional contact; QR opens the form directly | ✅ agreed |
| D4 | Device auth v1 = per-locker API key; HMAC in v2 | ✅ agreed (simple v1) |
| D5 | AI provider: Claude API for extraction and comparisons, no embeddings | ✅ agreed |
| D6 | Reservation via conditional UPDATE in the approve transaction | ✅ agreed |
| D7 | Repo layout as in §9 | ✅ agreed |
| D8 | Python 3.13 | ✅ agreed |
| D9 | Device API paths and DB design follow the revised proposal (§9.4, §9.5) | ✅ agreed |
| D10 | Frontend: HTML pages (Bootstrap) + JavaScript calling the JSON API (`/api/...`); FastAPI serves the page shells | ✅ agreed |
| D11 | ESP32 ↔ backend: plain HTTP + `X-Device-Key` for the demo (local network); HTTPS only if time allows | ✅ agreed |

## 11. Open questions for the team
- Locker codes: confirm 6 digits and the TTLs in §8 (Raphael).
- Who is notified when an item is `UNCLAIMED` after N days? (v1: admin list only.)
- Should the owner see the finder's optional contact after a successful pickup? (Proposed: no, v1 admin-only.)
