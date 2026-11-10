# PrivateFind: integration conflicts

Scope: keep Zohidjon's backend and connect the team's work. This is a practical demo integration checklist, not a security audit. Team snapshot: `codex/team-review`, commit `62e8c4f`.

The documented responsibilities are Zohidjon: AI/backend; Muslimbek: frontend; Simon: database/matching; Raphael: IoT/locker. The database and matching work overlap with the backend, so they require agreement with Simon rather than copying both implementations into one app.

## 1. Raphael: firmware and device API

| Interface | Your backend | Team firmware | Actual conflict / simple resolution |
|---|---|---|---|
| Validate URL | `POST /api/device/codes/validate` | Sketch uses configurable `BACKEND_URL`; example still points to `/locker/validate` | Correct the example URL. |
| Validate body | `{code: "123456"}` | `{device_id: "locker_01", code: "123456"}` | Compatible: your request model ignores the extra `device_id`. It can stay for now. |
| Device key | `X-Device-Key`; key identifies the locker | Same header, but example does not define `DEVICE_KEY` | Copy the key printed by your seed into the firmware configuration. The team's old default key will not match your new locker. |
| Successful validation | `{action: "open", compartment: 1, message: "Open box 1"}` | Requires `authorized: true`, `compartment: 1`, and `action: "deposit"` or `"pickup"` | **Blocker:** firmware rejects your valid response. Adapt its validation function to your response. |
| Deposit/pickup instruction | Response does not include the code's purpose | Uses `deposit`/`pickup` only to select the LCD instruction | Simplest option: show a common message such as “Use box, then #”. If separate instructions are wanted, add an optional `purpose` field to your response and read it in firmware. |
| State URL | `POST /api/device/compartments/1/state` | Uses `BACKEND_STATE_URL`, absent from the example | Define this URL in the example/configuration. |
| State body | `{occupied: true}` | `{device_id: "locker_01", occupied: true}` | Compatible: extra device ID is ignored. |
| State response | `{ok: true, message: "..."}` | Team API returns `{compartment: 1, state: "occupied"}`, but sketch checks only HTTP 200 | **No current firmware blocker** from the different JSON response. |
| Code length | Exactly six digits | Accepts 1–12 digits before submission | Issued six-digit codes work already. Optionally restrict keypad input to six for clearer behavior. |
| Compartment count | Seed creates two compartments | One servo, only compartment 1 accepted | **Blocker after box 1 is reserved:** backend can allocate box 2, which firmware rejects. Seed one compartment for this prototype. |

Do not change the state machine just to match internal names. The firmware does not consume backend state strings. Your backend can keep `DEPOSIT_PENDING` and its existing pickup flow.

The smallest firmware integration is therefore: correct URLs/key, accept `action=open/deny`, use a common instruction, and configure one compartment. No compatibility API or second locker implementation is necessary.

## 2. Muslimbek: browser/API contract

The fetched team branch has only an empty `frontend/frontend.txt`. These are differences from its documented/API expectations, **not confirmed bugs in frontend code**. There is no implemented frontend in that snapshot to inspect.

| Feature | Team API / README expectation | Your actual backend | What the frontend should use |
|---|---|---|---|
| Finder starts | `POST /api/deposit-sessions` with numeric `locker_id`, receive token | No deposit-session route; `GET /api/lockers/{locker_code}` returns availability and locations | Open locker `L1`, fetch its info, then submit directly. |
| Deposit fields | `token`, `location`, optional `category`, `note`, JSON `answers`, three `photos` | Required `locker_code`, `location`, `note`, `photos`; optional `finder_contact` | Build multipart from your fields. Finder answers/category are not stored by this endpoint; do not silently depend on them. |
| Deposit result | `code_expires_at` | `expires_at` | Display `deposit_code`, `compartment`, `expires_at`. |
| Images | Exactly three, 10 MB each; includes HEIC | 1–3, 5 MB each; JPEG/PNG/WebP | Frontend limits and accepted formats must follow your backend. Three photos still work within those limits. |
| Owner identity | `X-User-Id`, seeded username | Login/register with email/password, session cookie | Use `/api/auth/*`; send same-origin cookies. |
| Lost-report fields | `lost_from`, `lost_to`, `brand_model`, optional `description`, `unique_marks` | `lost_at`, separate `brand`/`model`, optional `color`; `description` required, min 3 characters | Use a single lost-time input and your fields. A time window is a feature decision, not an automatic field rename. |
| Report ID | `report_id` | `id` | Store the returned `id` for candidate/claim calls. |
| Candidate fields | `item_id`, `match_score`, `found_location`, `public_attributes`, `match_id` | `found_item_id`, `score`, `location`, `public_summary`, `color`, `breakdown` | Render your response directly; claims need `found_item_id`, not `match_id`. |
| Categories | `earphones`, `card` | `headphones`, `id_card`; also more categories | Use your vocabulary. Old values would fail validation. |
| Locations | Free text, e.g. `Gwanggaeto Hall, 3rd floor` | Configured codes, e.g. `library`, `engineering_building` | Populate a select from the locker-info `locations` list. |
| Errors | `response.detail` | `response.error.message` | Read your error envelope. |
| Admin audit | `/api/admin/audit-log`, optional `only_alerts` | `/api/admin/audit`, optional `entity_type`/`entity_id` | Use your route and fields; alert filtering is not currently the same feature. |
| Claims/admin review | Team API does not implement these routes | Your `/api/claims` and `/api/admin/claims` routes exist | Build these pages against your contract; there is no team claim API to preserve. |
| Status labels | Lowercase, e.g. `open`, `in_review` | Uppercase, e.g. `STORED`, `IN_REVIEW` | Use your values in filters/conditions; human-readable labels can differ. |

Serving the pages from the same FastAPI app is the simplest approach and matches the architecture. If a separate frontend development server is introduced, its origin/cookie setup will need configuration; this is not a current conflict because no such frontend is present.

## 3. Simon: database and matching

These parts run inside the backend; they are not independent API clients.

| Area | Team implementation | Your implementation | Integration consequence |
|---|---|---|---|
| Model imports | `backend.database.models`, synchronous `Session` | `app.modules.*.models`, async `AsyncSession` | Team services cannot be imported unchanged. Port selected logic into your existing modules with Simon. |
| IDs/columns | `item_id`, `report_id`, `locker_id` as primary-key names | Mostly `id`; foreign keys reference `*.id` | Same table names do not mean compatible schemas. |
| Finder session | `deposit_session` table, token relationship | No deposit sessions | Decide whether finder sessions are required; simplest is to keep your direct flow. |
| Found-item storage | Item points to compartment; historical items remain linked | Compartment stores current `found_item_id`; item also identifies locker | Team locker queries/relationships need adaptation, not just renaming. |
| Claim relationship | Claim references `match_candidate.match_id` | Claim directly references report and found item | Team claim/pickup helpers cannot plug in unchanged. |
| Attributes | Numeric `weight` 1/2/3, e.g. `colour` | `strength` generic/distinctive/strong; public `color` | Translate any reused data/logic; copy only attributes your contract supports. |
| Candidate scores | Partial scores 0–100 before weighting | Partial scores are weighted points, e.g. category max 25 | Do not combine the raw score columns or display both as if equivalent. |
| Matching inputs | Lost-time window, free-text location, public-attribute word matching | One lost time, configured location, structured fields, AI comparison | Keep one matching implementation. Agree with Simon which of his behaviors to port. |
| Semantic approach | Mock word-count embeddings, disabled by default; other factors rescaled | AI text comparison, no embeddings | Do not add an embedding service merely to combine repos. Use your existing provider. |
| Migrations/seed | Root `alembic/`, team schema and demo data | `backend/migrations/`, your schema and seed | Run only the migration/seed matching the chosen backend schema. |

For the school demo, the simplest proposal is your backend schema plus a **fresh, separate demo database**, with Simon reviewing it and contributing matching changes there. This avoids a data-conversion project. If the team's existing data must be retained, its conversion is a separate requirement; do not reset their database.

## 4. Small fixes needed in your own handoff

- `docs/design/api-contract.md` and the live route require a `note` form field. The architecture describes the finder note as optional. Make the endpoint accept a missing note, or explicitly make the UI require a note; agree one behavior before handing off the form.
- Your seed hardcodes two compartments. Match the team's one-compartment prototype.
- Your repo has no page routes/templates yet, even though the architecture proposes `/found/new?locker=L1`. Muslimbek needs to add the page layer; generating a QR link alone will not create that page.
- Claims use `found_item_id` and `lost_report_id`. Keep these exact names in Muslimbek's claim form rather than introducing aliases for the team's candidate model.

## 5. Minimal integration sequence

1. **Zohidjon + Simon:** agree to use your backend schema and one matching implementation; create a separate demo DB for it.
2. **Zohidjon:** adjust seed to one compartment and resolve optional-note behavior.
3. **Raphael:** update the configuration and validation-response handling to your device API. Keep existing state reporting.
4. **Muslimbek:** build the pages against your API contract/OpenAPI, using your payload names, dropdown values, cookie login, and error shape.
5. **Together:** run one real sequence: finder deposit → device opens → occupied report → owner report → candidates → claim → pickup → empty report.

No application code changed during this comparison. Verified directly against route/schema source, team firmware, both model sets, and local generated OpenAPI. Small schema probes confirmed that both device requests tolerate the extra `device_id` and that the deposit currently requires `locker_code`, `location`, `note`, and `photos`.
