# Backend Build Plan

Built one module at a time. Each step ends with passing tests (`uv run pytest`) before the next step starts.
References: [architecture.md](architecture.md) and [api-contract.md](api-contract.md).

| Step | Module | Contents | Tests | Done |
|---|---|---|---|---|
| 0 | scaffold + `core` | `pyproject.toml` (uv, Python 3.13), config, async DB session, error shape, `create_app()`, `/api/health` | health, error shape | ✅ |
| 1 | `shared` | `audit.log()`, photo storage (Pillow, private folder), in-memory rate limiter, `AIProvider` + `MockAIProvider` | storage, mock AI | ✅ |
| 2 | `identity` | register/login/logout/me, Argon2, session cookie, `current_user` / `require_admin` | auth flow | ✅ |
| 3 | `locker` | lockers, compartments, codes (HMAC hashes, TTL), device API, compartment state machine | codes, device flow | ✅ |
| 4 | `found_items` | `POST /api/deposits`, background AI extraction with retry, startup re-queue, admin item endpoints | deposit → STORED, AI retry | ✅ |
| 5 | `lost_reports` | create/list/get reports | CRUD, ownership | ✅ |
| 6 | `matching` | `policy.py` score, candidate search, `match_candidate` rows | policy unit tests, candidates API | ✅ |
| 7 | `claims` | verification `policy.py`, claim API, reservation, pickup code, admin decisions, cooldown | policy, end-to-end pickup | ✅ |
| 8 | `ai/claude` | real `ClaudeProvider` (vision + structured output), chosen with `AI_PROVIDER=claude` | mocked SDK test | ✅ |
| 9 | ops | Alembic initial migration, seed script, `docker-compose.yml` (MySQL), README run instructions | migration runs | ✅ |

**Test database:** SQLite in memory (`aiosqlite`), so tests run anywhere. The dev and demo database is MySQL 8 via Docker. The models only use portable types.

## Status (2026-10-02)
- **Done:** all 10 steps. 56 tests pass and ruff is clean. 26 endpoints are live at `/docs`.
- **Not yet verified:** the migration against real MySQL (Docker was not running; it was only tested on SQLite) and the `ClaudeProvider` against the live API (tested with a fake client only).
- **Next:**
  - frontend pages (Muslimbek) against `/docs`;
  - firmware (Raphael) against `/api/device/*`;
  - tune the match and verification thresholds with real photos (WBS 10.2).

## Team integration update (2026-11-10)

Adopt Simon's 13-table baseline plus an additive backend migration. Preserve async services,
map the existing browser fields to the team columns, and use Raphael's device request/response
format. Seed one compartment. See [team integration](team-integration.md).
The original 2026-10-02 status above is a historical checkpoint.
