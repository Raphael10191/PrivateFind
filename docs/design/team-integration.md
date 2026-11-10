# Team integration: database and firmware

Implemented 2026-11-10. This decision supersedes the earlier review's proposal to keep the original local schema and change the firmware response handling.

## Agreed direction

- **Simon:** database baseline, table/column names, foreign keys, lowercase enums, numeric attribute weights.
- **Raphael:** existing device route paths and request/response format.
- **Zohidjon:** async backend services, authentication, AI, verification, browser API.
- **Muslimbek:** frontend against the updated [API contract](api-contract.md).

The ORM models remain in their domain modules. Python attributes such as `User.id` map to Simon's actual columns such as `user.user_id`. This keeps existing browser field names while using the team's database structure.

## Database

Migration chain:

1. `c37e42452449`: Simon's 13-table baseline, imported from team commit `62e8c4f` (formatting only).
2. `c3c3ff57c7f3`: additive fields used by the existing backend.

The extra fields preserve existing functionality:

| Table | Added fields |
|---|---|
| `user` | `display_name` |
| `locker` | QR `code`, display `name` |
| `found_item` | `locker_id` for direct deposits, `finder_contact`, `ai_attempts`, `ai_error`, `public_summary`, `description` |
| `lost_report` | `color`, separate `brand` and `model` |
| `match_candidate` | `shown` (whether the owner was shown this candidate) |
| `claim` | `critical_conflict`, `decision_note` |
| `audit_log` | `actor_type` |

The `deposit_session` table is present. The current browser API still supports direct deposits without a finder token, using Simon's nullable `session_id`. Adding a finder-session API is not necessary for firmware integration.

Claims now reference `match_id`. Recalculating candidates updates rows in place so existing claims retain their references. Found items retain their compartment relationship as history; active occupancy is determined by item status. Attribute strength maps to Simon's numeric weight (generic=1, distinctive=2, strong=3). Stored partial match scores use Simon's 0–100 scale; the browser's `breakdown` still returns weighted points.

### Fresh database

Point `DATABASE_URL` at a new demo database, then run from `backend/`:

```powershell
uv run alembic upgrade head
uv run python -m scripts.seed --admin-email admin@privatefind.local --admin-password changeme123
```

This creates one compartment, device ID `locker_01`, and QR code `L1`. Save the printed device key for Raphael.

### Existing Simon database

Keep the original `SECRET_KEY` and device key if existing locker codes must continue working. Use an async connection URL (`mysql+asyncmy://...`) for this backend.

If Alembic already reports `c37e42452449`, `alembic upgrade head` applies only the additive revision. Existing IDs, claims, item notes and device-key hashes are preserved. The migration fills existing locker code/name from `device_id` and derives item locker IDs from their compartment or deposit session.

Running the seed afterwards attaches the chosen QR code/name to the existing device rather than creating a second device or replacing its key. The seed does not remove existing compartments. Existing team photos require `STORAGE_DIR` to point at their original upload root, because `storage_path` is relative to that root.

No database was reset or upgraded in place during implementation. Verification used separate temporary SQLite databases. If an existing database instead reports the old local revision `5f5a5099c355`, use a separate fresh demo database for this schema; do not stamp it as Simon's revision. The old local baseline is archived at `docs/reviews/legacy-local-initial-schema.py.txt` for reference.

## Firmware contract

The sketch can keep its current request/response handling:

```http
POST /api/device/codes/validate
X-Device-Key: <existing or seeded device key>
Content-Type: application/json

{"device_id":"locker_01","code":"123456"}
```

Accepted:

```json
{"authorized":true,"compartment":1,"action":"deposit"}
```

Pickup returns `action: "pickup"`. Denial returns:

```json
{"authorized":false,"compartment":null,"action":null}
```

After closing the door and pressing `#`:

```http
POST /api/device/compartments/1/state
X-Device-Key: <same key>
Content-Type: application/json

{"device_id":"locker_01","occupied":true}
```

Response: `{"compartment":1,"state":"occupied"}`; successful pickup reports `occupied:false` and returns state `free`.

The firmware's existing example configuration is incomplete. Its `secrets.h` needs:

```cpp
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* DEVICE_KEY = "KEY_FOR_LOCKER_01";
const char* BACKEND_URL = "http://YOUR_BACKEND_IP:8000/api/device/codes/validate";
const char* BACKEND_STATE_URL = "http://YOUR_BACKEND_IP:8000/api/device/compartments/1/state";
```

The backend also accepts `/locker/validate` as an alias of code validation, so the older example URL works without a route change in the firmware. Both URLs use the same handler and response. The missing key and state URL still need to be configured. No firmware logic changes are needed. Run the backend on the laptop's LAN address with `--host 0.0.0.0` so the ESP32 can reach it.

## Scope and verification

This adopts Simon's database, not a second copy of his synchronous services or mock embedding implementation. The existing async matching/AI policies remain in place. Browser payload names remain the same; statuses now use lowercase values and the finder note may be omitted.

Tests exercise deposit-to-pickup with foreign keys enabled, firmware's exact JSON fragments, one-compartment allocation, candidate refresh with existing claims, pickup-code replacement, and upgrading/downgrading a populated Simon database. MySQL execution, live AI and physical hardware still require a team integration run.
