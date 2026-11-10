# PrivateFind: team repository review

Reviewed on 2026-11-10 (Asia/Seoul).

## Conclusion

The team repository contains useful database, deposit, matching, audit, and ESP32 work. It is an incomplete backend integration baseline. The local backend implements substantially more of the agreed architecture, including authentication, AI orchestration, claims, and admin review. Neither implementation is ready to be treated as a finished, integrated system.

Recommended direction: retain the local modular backend as the integration base, adapt the team's firmware and useful database/matching/alert behavior, and agree one API contract and schema before combining code. A wholesale merge would introduce overlapping implementations and incompatible models rather than finish integration.

## What was fetched and compared

- Team source: `https://github.com/Raphael10191/PrivateFind`, branch `main`, commit `62e8c4fc8f0b05bc2968ff6be9cc1434323ea3da` (2026-11-08).
- Imported into local branch `codex/team-review`. Remote branch inventory contained only `main` at review time.
- Current checkout remains `main`; existing modified and untracked work was preserved. Nothing was pushed or merged.
- The repositories have no common Git ancestor. The team branch is an independent history, not a feature branch based on this checkout.
- Local baseline: the actual working tree, including the untracked `backend/`, plus `README.md`, `docs/TASKS.md`, and `docs/design/{architecture,api-contract,backend-plan}.md`. Comparing only committed `main` would miss almost all the local implementation.
- Team code was exported to an isolated snapshot for inspection and tests. Review probes were added only to that snapshot.

## What the team has built

The history contains a database migration/model contribution, a subsequent deposit/matching/security/audit contribution, and ESP32 updates. Current code provides anonymous deposit sessions, photo persistence, compartment reservations, expiring single-use codes, lost reports, ranked public candidates, device validation/state reporting, and admin audit queries.

There is no working frontend in this branch: `frontend/frontend.txt` is empty. The local backend also has no implemented page/template layer. Swagger API documentation is currently the usable interface.

## Main differences

| Area | Current local working tree | Team repository |
|---|---|---|
| Structure | Async FastAPI, six domain modules, separate schemas/policies, `uv.lock`, Python 3.13 requirement | Mostly synchronous SQLAlchemy/services, centralized models, unpinned requirements, no declared Python version requirement |
| Authentication | Email/password registration and login, signed session cookie, owner/admin dependencies | Password hashing/authentication helper exists; routes trust caller-supplied `X-User-Id`; no login/register API |
| Finder flow | Direct deposit using `locker_code`; optional finder contact | First requests a token using numeric `locker_id`; then deposits using token and finder answers |
| Photos | 1–3 images, 5 MB each, decoded/resized/re-encoded as JPEG, EXIF removed | Exactly 3 images, 10 MB each, JPEG/PNG/WebP/HEIC, original bytes saved after header check |
| AI | Mock and Claude adapters, background extraction, retry, startup requeue, admin retry/correction | Attribute-saving/failure helpers only; no connected extraction worker/provider; new items remain pending without external integration |
| Matching | Fixed location vocabulary; one lost timestamp; color/brand/model; AI text comparison | Free-text building/location overlap; lost-time window; weighted public-attribute word matching; word-count mock embeddings disabled by default |
| Claims | Evidence verification, conditional item reservation, owner APIs, cooldown, pickup reissue, admin decisions | Claim/evidence tables and pickup helper exist; no claim submission/verification/admin decision routes |
| Database | 12-table variant without deposit sessions; modular models; uppercase lifecycle strings | 13 tables including deposit sessions; centralized enum models with lowercase values; different columns and relationships |
| Device API | Device key identifies locker; `{action: "open"|"deny", compartment?, message}` | Requires `device_id`; `{authorized, compartment, action: "deposit"|"pickup"}` |
| Device hardware | No firmware in current checkout | One-compartment ESP32 sketch, keypad/LCD/servo, IR and ultrasound agreement |
| Admin | Items, private photos, attributes, AI retry, claims, audit | Audit log and alerts only |
| Errors/time | `{error: {code, message}}`; UTC convention | FastAPI `detail`; naive local server timestamps |

These are integration decisions, not all defects. The team implementation often follows the earlier proposal while the local architecture records later simplifications. In particular, deposit sessions, embedding plans, and time-window inputs need an explicit team decision.

## Confirmed team defects and blockers

### 1. High: any caller can impersonate an owner or admin

[`backend/api/deps.py:15–38`](https://github.com/Raphael10191/PrivateFind/blob/62e8c4fc8f0b05bc2968ff6be9cc1434323ea3da/backend/api/deps.py#L15) loads a user by the unverified `X-User-Id` header. Supplying an administrator's ID grants admin access without a password or session. A review probe confirmed a 200 response from the admin audit endpoint using only that ID.

This is documented as temporary, but the admin role check does not provide security until identity is authenticated. Replace it with real session authentication before any shared deployment.

### 2. High: the checked-in firmware setup cannot build as documented

[`secrets.example.h`](https://github.com/Raphael10191/PrivateFind/blob/62e8c4fc8f0b05bc2968ff6be9cc1434323ea3da/iot/locker_mvp/secrets.example.h) defines only Wi-Fi credentials and an obsolete `/locker/validate` URL. The sketch also references `DEVICE_KEY` and `BACKEND_STATE_URL`, which the example does not define. Creating `secrets.h` from this example therefore leaves undefined identifiers, and its validation URL targets a removed route.

Add both missing constants and the current API URLs. This is a source-level finding; an Arduino toolchain/hardware build was not performed.

### 3. High: keypad alerts do not limit guessing

[`check_code()` and `_alert_if_many_wrong_codes()`](https://github.com/Raphael10191/PrivateFind/blob/62e8c4fc8f0b05bc2968ff6be9cc1434323ea3da/backend/services/locker.py#L185) log failures and an alert, but do not enforce a wait period. Device routes have no equivalent of the finder/owner IP limiter. A probe submitted eight wrong codes and then successfully used the correct code immediately.

Enforce the agreed per-locker code-attempt limit; keep the audit alert as an additional feature.

### 4. High: expired pickup codes strand the reservation

[`create_pickup_code()`](https://github.com/Raphael10191/PrivateFind/blob/62e8c4fc8f0b05bc2968ff6be9cc1434323ea3da/backend/services/locker.py#L164) requires an `OCCUPIED` compartment and changes it to `PICKUP_RESERVED`. Expiry recovery handles deposit reservations only. When a pickup code expires, the compartment stays `PICKUP_RESERVED`, the code cannot open it, and calling the pickup helper again fails because it requires `OCCUPIED`. A service-level probe confirmed this sequence.

Implement authorized pickup-code replacement/revocation and reservation recovery. The team branch also has no owner pickup-code endpoint yet.

### 5. Medium: normal UTC timestamps cause a server error

[`create_lost_report()`](https://github.com/Raphael10191/PrivateFind/blob/62e8c4fc8f0b05bc2968ff6be9cc1434323ea3da/backend/services/lost_reports.py#L25) compares parsed datetimes with naive `datetime.now()`. Sending ISO timestamps ending in `Z` raises `TypeError` for comparing offset-aware and offset-naive values. This was reproduced through the API test client.

Normalize timestamps to a single UTC representation before validation/storage. Merely setting the deployment timezone does not fix mixed datetime types.

### 6. Medium: photo validation accepts corrupt files and preserves metadata

[`_looks_like_image()`](https://github.com/Raphael10191/PrivateFind/blob/62e8c4fc8f0b05bc2968ff6be9cc1434323ea3da/backend/services/deposits.py#L132) checks a few leading bytes rather than decoding an image. The team's own flow fixture uses JPEG header bytes followed by plain text, and a probe confirmed these are accepted and stored as photos. This can break downstream image processing. Saving original files also retains any EXIF/GPS metadata they contain.

Decode and re-encode uploads, and enforce upload bounds while reading. Both codebases currently read each uploaded file fully before checking its size.

### 7. High integration gap: the demonstrated pickup flow bypasses ownership verification

The team's `tests/test_flow.py` manually inserts an approved claim directly into the database before generating a pickup code. Its passing “full flow” test therefore verifies deposit/matching/device plumbing, not real owner claim submission or proof of ownership. There is no claim router or extraction job in `backend/main.py` to complete these paths.

Do not report AI extraction or ownership verification as completed based on this test. Integrate the actual APIs and test through them.

## Further source-level reliability concerns

- **Code consumption race, both backends:** validation reads an active code and later writes its used status without a conditional atomic consume or row lock around validation. Concurrent requests can potentially both authorize. Sequential replay tests do not establish concurrent safety. Confirm on MySQL and make consumption atomic.
- **Firmware recovery:** in `VERIFYING_STATE`, sensor disagreement has no timeout/cancel path; keypad input is ignored. The servo is commanded closed only after a successful backend state report. Network failure or persistently disagreeing sensors can therefore leave the device in verification with the servo commanded open. Add bounded recovery and restart/reconciliation behavior; hardware consequences need bench testing.
- **Firmware parsing:** response acceptance relies on JSON substrings rather than parsed values. Whitespace changes can reject otherwise valid responses. Use a JSON parser and validate compartment/action fields.
- **Blocking work in async route:** the team's async deposit route calls synchronous DB/file functions directly. Consider this when choosing the final concurrency model; retain the agreed async backend if that remains the project direction.
- **Repository hygiene:** a compiled `backend/__pycache__/main.cpython-312.pyc` is committed. Remove generated bytecode and lock dependencies for reproducible installs.

## Issues in the local baseline too

The local implementation is a better fit for the current architecture, but its passing suite does not establish production readiness.

1. **Serial verification loses letters.** `backend/app/modules/claims/policy.py:50` strips all non-digits. A direct probe returned `True` for stored `AB1234` versus claimed `XY1234`, and `False` for identical `ABCD` values. The AI extraction instruction says to store the last four *characters*. Preserve normalized alphanumeric characters and add meaningful regression cases.
2. **Default signing secret is predictable.** `backend/app/core/config.py:12` defaults to `change-me`; the same secret signs session cookies and hashes codes/device keys. Explicit configuration is required before a shared deployment, ideally with startup rejection of the default.
3. **MySQL and live Claude remain unverified.** Existing local tests use SQLite and a fake AI client. This agrees with the limitation already recorded in `backend-plan.md`; neither migration behavior under MySQL nor a real provider request was verified in this review.
4. **The local backend is untracked.** It exists on disk but is not in the current committed baseline. Preserve it in a reviewed commit/branch before integration so the team can actually consume it.

## Verification performed

| Check | Result |
|---|---|
| Local existing suite | **56 passed** |
| Team existing suite, isolated snapshot | **19 passed** |
| Additional team review probes | **5 confirmed behaviors**: impersonation, corrupt photo acceptance, missing keypad throttle, UTC exception, expired pickup reissue failure |
| Local serial comparison probes | Two incorrect outcomes reproduced |
| Team branch inventory | Only `main` advertised |
| MySQL integration / live AI / firmware compile / physical hardware | Not performed |

The five review probes assert the observed bad behavior, so their passing result confirms defects rather than correctness. Team tests reused the installed local Python environment; this was not a fresh installation from the team's unpinned requirements. Initial sandbox runs encountered Windows temporary-directory/thread execution problems; successful suites ran outside the sandbox. The stalled runs were stopped.

## Recommended integration order

1. Preserve the local backend in version control, and agree the canonical architecture/API with the team. Use the current local modular implementation as the proposed base.
2. Agree the device response schema first. The team's firmware expects `authorized` and `deposit/pickup`; the local backend returns `action=open/deny`. It will not open against that backend unchanged.
3. Adapt firmware configuration, parsing, and failure recovery. Decide whether the demo uses one physical compartment or two before seeding lockers.
4. Reconcile one database schema and write an explicit migration/data mapping if existing team data matters. The two initial migrations are independent baselines and cannot simply be run together.
5. Bring over useful team behavior deliberately: finder answers, location matching, lost-time windows, claim alerts, and resolving the lost report after actual pickup. Decide which changes are in scope rather than copying parallel services.
6. Fix authentication, code consumption/throttling/recovery, and serial validation; then exercise real login → report → candidates → evidence → approval/review → pickup through APIs.
7. Validate migrations/concurrency on MySQL, one live AI extraction and comparison, and physical deposit/pickup plus network/sensor failures. Build the frontend against the agreed contract.

Suggested ownership: Zohidjon for auth/AI/claims and integration; Simon for schema/matching/MySQL/alerts; Raphael for firmware/device recovery; Muslimbek for pages after the API contract is fixed.
