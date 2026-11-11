# PrivateFind API: frontend integration guide

Updated **2026-11-11** against the integrated backend. This describes implemented behavior, including current limitations. Examples contain synthetic data. IDs, codes, timestamps, and scores are examples; use values returned by your server.

## Contents

1. [Connection and authentication](#1-connection-and-authentication)
2. [Endpoint index](#2-endpoint-index)
3. [Errors and limits](#3-errors-and-limits)
4. [Authentication APIs](#4-authentication-apis)
5. [Finder APIs](#5-finder-apis)
6. [Lost reports and candidates](#6-lost-reports-and-candidates)
7. [Claims and pickup](#7-claims-and-pickup)
8. [Admin APIs](#8-admin-apis)
9. [Response models](#9-response-models)
10. [Device APIs and simulation](#10-device-apis-and-simulation)
11. [Frontend workflows](#11-frontend-workflows)
12. [Vocabularies and states](#12-vocabularies-and-states)
13. [Testing and unsupported features](#13-testing-and-unsupported-features)

Importable files:

- [OpenAPI 3.1 snapshot](openapi.json): all 27 canonical operations plus the legacy device alias; includes request/response schemas and documentation-only cookie/device auth and custom error annotations.
- [Postman collection](postman-collection.json): all 28 operations, with example bodies and variables.
- Live Swagger UI: `http://localhost:8000/docs`. Runtime schema: `/openapi.json`.

The export corrects metadata that FastAPI does not infer automatically: custom errors, cookie authorization, JPEG photo responses, heartbeat/retry response shapes, and the hidden alias. It does not change runtime behavior. Regenerate from `backend/` with `uv run python -m scripts.export_api_docs`.

## 1. Connection and authentication

### Base URL

Docker publishes `http://localhost:8000` by default. For a shared server, replace `localhost` with its network address. Base URL examples do **not** include `/api`; paths below do. `GET /api/health` returns `200 {"status":"ok"}` without authentication.

Always use the same hostname for login and later calls. `localhost` and `127.0.0.1` are different cookie hosts.

### Browser login

- Register/login sets a signed cookie named `session`. No JWT or bearer token is returned.
- Cookie: `HttpOnly`, `SameSite=Lax`, default lifetime 7 days. JavaScript does not read or store it.
- Use `credentials: "same-origin"` with the recommended same-origin setup below.
- On app load, call `GET /api/auth/me`. A 401 means show login; a 200 gives the current user/role.
- Register creates an `owner`. Admins are created by the seed script, not by a public role field.
- `owner` and `admin` accounts can use the account endpoints; only `admin` can use `/api/admin/*`.
- Finder deposit is anonymous. Do not require login for that page.
- The old `X-User-Id` mechanism is not supported. Device keys belong to firmware/test tools, not frontend bundles.

### Separate frontend dev server

**The backend currently has no CORS middleware.** A frontend at port 5173 calling port 8000 directly is cross-origin. Adding `credentials: "include"` alone does not fix this.

Use relative `/api/...` calls and a development proxy. For example, in a Vite frontend:

```ts
import { defineConfig } from "vite";

export default defineConfig({
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000", // or the shared backend server address
        changeOrigin: true,
      },
    },
  },
});
```

Requests, cookies and private-photo URLs then use the frontend origin. For deployment, serve frontend and `/api` under one origin using a reverse proxy. There is no frontend static-file hosting implemented in the current backend. See [Vite's proxy reference](https://vite.dev/config/server-options.html#server-proxy).

### Fetch helper

```ts
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields: Array<{ field: string; message: string }> = [],
  ) { super(message); }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  // Let the browser set multipart boundaries for FormData.
  if (typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...init, headers, credentials: "same-origin",
  });
  const contentType = response.headers.get("content-type") ?? "";
  const body = response.status === 204 ? undefined
    : contentType.includes("application/json") ? await response.json()
    : await response.text();
  if (!response.ok) {
    throw new ApiError(
      response.status, body?.error?.code ?? "request_failed",
      body?.error?.message ?? `Request failed (${response.status})`,
      body?.error?.fields ?? [],
    );
  }
  return body as T;
}

// Examples:
await api("/api/auth/login", {
  method: "POST", body: JSON.stringify({ email, password }),
});
await api<void>("/api/auth/logout", { method: "POST" });
```

Network failures may throw a native fetch error. Handle those separately from `ApiError`. For photo blobs, use `fetch`/`response.blob()` rather than the JSON helper.

### Types, nulls and times

- IDs are numbers. Locker identifiers such as `L1` are strings. Device codes are **strings**, including leading zeroes (`"004821"`).
- Optional request fields can be omitted. Nullable fields can be `null` where their schema permits it. Responses generally include nullable keys with `null`; do not assume they are absent.
- JSON request/response names use `snake_case`. Standard API lists are plain arrays; no pagination wrapper.
- Send `lost_at` in **UTC**, e.g. `new Date(input).toISOString()`. Convert local date/time input to UTC before sending it.
- Current response timestamps are naive UTC ISO strings, e.g. `"2026-11-11T08:00:00"`, without `Z`. Normalize them before browser date parsing. Do not send non-UTC offsets: the current report service strips timezone information rather than converting it.

```ts
export function utcDate(value: string): Date {
  return new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`);
}
```

`found_date` is a calendar date (`YYYY-MM-DD`), not a timestamp. Render it as a date. Use the server's `expires_at` values for code countdowns; defaults are deposit 15 minutes and pickup 48 hours.

## 2. Endpoint index

`Account` means logged-in owner or admin. Device calls are for firmware or a separate testing tool.

| Method | Path | Access | Success / response |
|---|---|---|---|
| GET | `/api/health` | Public | 200 `{status:"ok"}` |
| POST | `/api/auth/register` | Public | 201 User |
| POST | `/api/auth/login` | Public | 200 User |
| POST | `/api/auth/logout` | Public/current session | 204, no body |
| GET | `/api/auth/me` | Account | 200 User |
| GET | `/api/lockers/{locker_code}` | Public | 200 LockerInfo |
| POST | `/api/deposits` | Public | 201 Deposit |
| POST | `/api/lost-reports` | Account | 201 LostReport |
| GET | `/api/lost-reports` | Account | 200 LostReport[] |
| GET | `/api/lost-reports/{report_id}` | Account, own report | 200 LostReport |
| GET | `/api/lost-reports/{report_id}/candidates` | Account, own report | 200 Candidate[] |
| POST | `/api/claims` | Account | 201 Claim, including rejected/review outcomes |
| GET | `/api/claims` | Account | 200 Claim[] |
| GET | `/api/claims/{claim_id}` | Account, own claim | 200 Claim |
| POST | `/api/claims/{claim_id}/pickup-code` | Account, own approved claim | 200 PickupCode |
| GET | `/api/admin/items` | Admin | 200 AdminItem[] |
| GET | `/api/admin/items/{item_id}` | Admin | 200 AdminItem |
| PUT | `/api/admin/items/{item_id}/attributes` | Admin | 200 AdminItem |
| POST | `/api/admin/items/{item_id}/retry-ai` | Admin | 202 `{ok:true}` |
| GET | `/api/admin/items/{item_id}/photos/{photo_id}` | Admin | 200 JPEG bytes |
| GET | `/api/admin/claims` | Admin | 200 AdminClaim[] |
| GET | `/api/admin/claims/{claim_id}` | Admin | 200 AdminClaim |
| POST | `/api/admin/claims/{claim_id}/decision` | Admin | 200 Claim |
| GET | `/api/admin/audit` | Admin | 200 AuditEntry[] |
| POST | `/api/device/codes/validate` | Device key | 200 CodeResult (open/deny decision) |
| POST | `/api/device/compartments/{number}/state` | Device key | 200 CompartmentState |
| POST | `/api/device/heartbeat` | Device key | 200 `{ok,server_time}` |
| POST | `/locker/validate` | Device key | Exact alias of device code validation |

Path parameters ending in `_id`, plus `number`, are integers. An invalid integer produces 422. IDs do not identify database column names for frontend purposes: use the API names above.

## 3. Errors and limits

Handled business/auth/HTTP errors:

```json
{"error":{"code":"compartment_unavailable","message":"No free compartment in this locker."}}
```

Validation example:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Invalid request.",
    "fields": [{"field":"password","message":"String should have at least 8 characters"}]
  }
}
```

Nested field paths can look like `evidence.0.value`. Match `code`, not human-readable messages. `fields` is only provided for validation errors. Unexpected exceptions/AI comparison failures can still produce a plain 500 response; do not assume every error is JSON. There is no `Retry-After` header or cooldown end-time field.

| HTTP | Code | Typical trigger / UI action |
|---|---|---|
| 401 | `not_authenticated` | Session missing/expired; show login. |
| 401 | `invalid_credentials` | Wrong login; show the returned message. |
| 401 | `invalid_device_key` | Device key missing/wrong or request device ID does not match it. |
| 403 | `forbidden` | Account is not an admin. |
| 404 | `not_found` | Unknown resource; another user's report/claim is also hidden as 404. |
| 405 | `not_allowed` | Wrong HTTP method. |
| 409 | `email_taken` | Registration email already exists. |
| 409 | `compartment_unavailable` | Locker filled between checking availability and deposit submission. |
| 409 | `not_a_candidate` | Candidate endpoint was not called, or selected item was not in its latest shown set. |
| 409 | `item_unavailable` | Item no longer `open`, including a competing approval. Refresh candidates. |
| 409 | `claim_exists` | This account already has a review/approved claim for the item. Show existing claim. |
| 409 | `pickup_not_available` | Claim not approved or item no longer reserved. Refresh claim/report. |
| 409 | `item_not_in_locker` | Compartment not available for pickup-code issuance. |
| 409 | `not_in_review` | Admin tries deciding a claim that is no longer in review. Refresh queue. |
| 409 | `ai_already_done` | Retry requested for an already completed extraction. Refresh item. |
| 422 | `validation_error` | Missing fields, invalid enum/type/length/email, malformed JSON. |
| 422 | `invalid_location` | Location is outside the configured list. |
| 422 | `invalid_photo` | Wrong count/type/size or invalid image bytes. |
| 429 | `rate_limited` | Login or anonymous deposit rate exceeded. |
| 429 | `claim_cooldown` | Too many rejected claims for this user and item. |

Default limits (server configuration may change them):

- Login: 10 attempts per client IP per minute, including successful calls.
- Deposits: 5 submissions per client IP per 10 minutes, including submissions rejected by the service.
- Claims: after 3 rejected claims by the same user on the same item in the preceding 24 hours, further submissions get 429.
- Device: 5 invalid-code lookups per locker per minute; subsequent validation returns HTTP 200 with `authorized:false`.

There is no global 30-requests/minute limit on the integrated browser APIs. Avoid automatic retries of submissions: a request could have succeeded even when the connection was lost.

## 4. Authentication APIs

### POST `/api/auth/register`

JSON:

```json
{"email":"owner@example.com","password":"secret123","display_name":"Ana"}
```

| Field | Required | Validation |
|---|---|---|
| `email` | Yes | Email address; normalized to lowercase by the service. |
| `password` | Yes | 8–128 characters. |
| `display_name` | No | String up to 100 characters or null; default null. |

Returns **201 User**, already logged in via cookie. Errors: 409 `email_taken`, 422 validation. Do not send a role or username.

### POST `/api/auth/login`

JSON: `{"email":"owner@example.com","password":"secret123"}`.

Both fields are required; email must be valid. Returns **200 User** and sets/replaces the session cookie. Errors: 401 `invalid_credentials`, 422 validation, 429 `rate_limited`.

### POST `/api/auth/logout`

No body. Clears the session and returns **204 with no JSON body**, including when already logged out. Clear cached user/private-page state in the frontend.

### GET `/api/auth/me`

No body. Returns **200 User** or 401. Use it to restore navigation and role state after page refresh.

**User**:

```json
{"id":1,"email":"owner@example.com","display_name":"Ana","role":"owner"}
```

`id` number, `email` string, `display_name` string|null, `role` `owner|admin`.

## 5. Finder APIs

### GET `/api/lockers/{locker_code}`

Example: `/api/lockers/L1`. No authentication. Returns **200 LockerInfo**, or 404.

```json
{
  "code":"L1", "name":"Library smart locker", "location":"library",
  "free_compartments":1,
  "locations":["library","student_center","engineering_building","lecture_hall","cafeteria","gym","dormitory","outdoor","other"]
}
```

Populate the find-location selector from `locations`; these are valid **found/lost locations**, not a list of lockers. If `free_compartments` is zero, disable deposit. Check again when opening the page; still handle 409 on submission because availability can change.

### POST `/api/deposits`

Use `multipart/form-data`, not JSON.

| Form field | Required | Validation/default |
|---|---|---|
| `locker_code` | Yes | String, max 20; e.g. `L1`. |
| `location` | Yes | String, max 50; value from `locations`. |
| `photos` | Yes | Repeat this **same field name** for 1–3 files. JPEG, PNG or WebP; each at most 5 MiB (5,242,880 bytes); must decode as an image. |
| `note` | No | Max 500 characters; defaults to empty string. |
| `finder_contact` | No | String max 200 or omitted; admin-only, never shown to owners. |

```ts
type Deposit = {
  item_id: number;
  compartment: number;
  deposit_code: string;
  expires_at: string;
};

const form = new FormData();
form.append("locker_code", "L1");
form.append("location", location);
form.append("note", note);
for (const file of files) form.append("photos", file);
if (finderContact) form.append("finder_contact", finderContact);
const result = await api<Deposit>("/api/deposits", { method: "POST", body: form });
```

Do not set `Content-Type` manually. Do not use `photos[]`, a JSON base64 array, `token`, `answers`, or `category`; those are not supported deposit fields in this backend. HEIC/GIF are unsupported.

**201 Deposit**:

```json
{"item_id":1,"compartment":1,"deposit_code":"004821","expires_at":"2026-11-11T08:15:00"}
```

Show compartment, code and expiry. The response means **code issued**, not that the physical item is already inside. AI runs after the response; physical storage is confirmed separately by the ESP32. There is no public deposit-status or item-detail endpoint for the finder to poll. The frontend must not call device endpoints to pretend a physical deposit happened outside a test tool.

Errors: 404 unknown locker; 409 no compartment; 422 photo/location/validation; 429 rate limit. Failed AI extraction does not undo an accepted deposit; an admin can retry/correct it.

## 6. Lost reports and candidates

All require a session. Access to another user's report returns 404.

### POST `/api/lost-reports`

```json
{
  "category":"phone", "location":"library", "lost_at":"2026-11-11T06:00:00Z",
  "color":"black", "brand":"Samsung", "model":null,
  "description":"Black Samsung phone with a cat sticker"
}
```

| Field | Required | Validation/default |
|---|---|---|
| `category` | Yes | Category vocabulary in section 12. |
| `location` | Yes | Configured location code; max 50 characters. |
| `lost_at` | Yes | ISO datetime. Send UTC. Single instant, not a `lost_from/lost_to` range. |
| `description` | Yes | 3–1000 characters. |
| `color` | No | Color vocabulary or null; default null. |
| `brand` | No | String max 50 or null; default null. |
| `model` | No | String max 100 or null; default null. |

Returns **201 LostReport**. Errors: 401, 422 validation/invalid location. `brand_model` and `unique_marks` are not input fields; put additional details in `description` and use separate brand/model inputs.

### GET `/api/lost-reports`

Returns **200 LostReport[]**, only the current account's reports, newest ID first. Empty state is `[]`. No query filters or pagination.

### GET `/api/lost-reports/{report_id}`

Returns **200 LostReport**; 401 or 404 if unavailable. Poll this at a modest interval after pickup if the page needs to detect `resolved`.

### GET `/api/lost-reports/{report_id}/candidates`

Returns **200 Candidate[]**, up to 3 candidates with score at least 60, highest first. `[]` is a successful “no candidates yet” result. No query/body.

This call recalculates matches and records which items were shown. **Call it before submitting a claim.** Only physically stored (`open`) items of the same category are considered. An item may not appear yet if it is not deposited, AI has not assigned its category, its score is too low, or it is reserved/returned.

Candidate summaries contain public data only: no photo URL, finder contact, private description, evidence or serial fragments. Display `score` and optionally `breakdown`; the score ranks matches and is not proof of ownership.

Errors: 401, 404; unexpected AI comparison failure may produce 500. Refresh is a GET but recalculates server-side matching; do not poll rapidly.

**LostReport**:

```json
{
  "category":"phone", "location":"library", "lost_at":"2026-11-11T06:00:00",
  "color":"black", "brand":"Samsung", "model":null,
  "description":"Black Samsung phone with a cat sticker",
  "id":2, "status":"open", "created_at":"2026-11-11T08:05:00"
}
```

Contains all report input fields, numeric `id`, lowercase `status`, and UTC `created_at`.

**Candidate**:

```json
{
  "found_item_id":1, "score":100,
  "breakdown":{"category":25,"location":15,"time":15,"attributes":25,"semantic":20},
  "category":"phone", "color":"black", "location":"library",
  "found_date":"2026-11-11", "public_summary":"Black Samsung phone"
}
```

`score` is an integer 0–100. `breakdown` fields are weighted numeric points (maxima 25/15/15/25/20); `color` and `public_summary` can be null. Use `found_item_id` in the claim. No `match_id` is exposed or required.

## 7. Claims and pickup

### POST `/api/claims`

Session required. The report must belong to the current user and the item must have been shown by the candidate endpoint.

```json
{
  "lost_report_id":2, "found_item_id":1,
  "evidence":[
    {"type":"serial_suffix","value":"4821"},
    {"type":"sticker_or_mark","value":"cat sticker on the back"}
  ]
}
```

Both IDs are required integers. `evidence` is required, **1–8 objects**. Each has a vocabulary `type` and a `value` of 1–200 characters.

Returns **201 Claim even if the verdict is `rejected` or `in_review`**. Check `status`; a fulfilled fetch is not necessarily ownership approval.

- `approved`: show pickup code/compartment/expiry when included.
- `in_review`: show the returned message, then allow checking claim status later.
- `rejected`: show the generic message and allow a permitted retry. Do not infer which evidence was wrong.

Errors: 401; 404 report/item missing; 409 `not_a_candidate`, `item_unavailable`, `claim_exists`, `item_not_in_locker`; 422; 429 `claim_cooldown`; unexpected comparison failure may produce 500.

### GET `/api/claims`

Returns **200 Claim[]**, current account only, newest first; empty state `[]`. No filtering/pagination. Pickup credentials are null in this response, including for approved claims.

### GET `/api/claims/{claim_id}`

Returns **200 Claim**, own claim only. Errors 401/404. Poll at e.g. 5–10 seconds while waiting for review, stop on page unmount, and stop when a terminal decision arrives. Poll intervals are a frontend suggestion, not a backend SLA.

### POST `/api/claims/{claim_id}/pickup-code`

No body. Own approved claim whose item is still `reserved`. Returns **200 PickupCode**:

```json
{"compartment":1,"pickup_code":"006142","expires_at":"2026-11-13T08:10:00"}
```

Each successful call **replaces/invalidate older unconsumed pickup codes**. Request on a deliberate “Get new pickup code” action, not on every render or poll. Errors: 401/404, 409 `pickup_not_available` or `item_not_in_locker`, 422 invalid path ID.

**Claim** (auto-approved POST example):

```json
{
  "id":3, "found_item_id":1, "lost_report_id":2, "status":"approved",
  "message":"Ownership verified. Use the pickup code at the locker.",
  "created_at":"2026-11-11T08:10:00", "compartment":1,
  "pickup_code":"006142", "pickup_expires_at":"2026-11-13T08:10:00"
}
```

`compartment`, `pickup_code`, `pickup_expires_at` are nullable. They are populated only on the claim-submission response that auto-approves it. List/detail and admin decision responses do not return these credentials. After an admin approval, the owner must call `/pickup-code`.

Claims remain `approved` after successful collection. **Use the linked report's `resolved` status to display pickup completion**, not an invented claim status such as `collected`. The report becomes resolved only when the device confirms pickup with `occupied:false`.

## 8. Admin APIs

All require a logged-in admin. Common errors are 401/403; details for a missing item/claim/photo return 404. Use lowercase status values.

### GET `/api/admin/items`

Optional query fields: `status` and `ai_status` (strings). Omit for all; combine filters with `&`:

`/api/admin/items?status=open&ai_status=failed`

Returns **200 AdminItem[]**, newest first. No pagination; do not send invented `page`/`search` parameters. Use only status values from section 12; filters are not strongly enum-validated by these routes.

### GET `/api/admin/items/{item_id}`

Returns **200 AdminItem** with private fields and `photo_ids`. This is the endpoint an admin can poll while `ai_status` is pending. Do not expose it on an owner/finder page.

### PUT `/api/admin/items/{item_id}/attributes`

```json
{
  "category":"phone", "public_summary":"Black Samsung phone",
  "attributes":[
    {"name":"color","value":"black","visibility":"public"},
    {"name":"brand","value":"Samsung","visibility":"public"},
    {"name":"serial_suffix","value":"4821","visibility":"private","strength":"strong"}
  ]
}
```

| Field | Required | Rule |
|---|---|---|
| `category` | Yes | Category vocabulary. |
| `attributes` | Yes | Array of 0–30 Attribute objects. **Replaces the entire list**, not a patch/merge. |
| `public_summary` | No | Max 200 or null. Omitted/null keeps the existing summary; empty string sets it empty. |

Attribute: required `name` (max 30), `value` (max 200), `visibility` (`public|private`); optional nullable `strength` (`generic|distinctive|strong`) and `confidence` (number). `confidence` is accepted by the input schema but **ignored by this admin handler**. Missing/null strength becomes generic (weight 1). Response attributes have `source` stored internally as admin, but `source` is not exposed.

Use public `color` and `brand`, and the evidence-type names for private details. Keeping serials/contents/marks out of the public summary is the admin UI's responsibility when editing it.

Returns **200 AdminItem**. Marks extraction `done`, clears its error. Errors 401/403/404/422. An empty list deliberately removes all attributes.

### POST `/api/admin/items/{item_id}/retry-ai`

No body. Returns **202 `{"ok":true}`**, then extraction runs in the background. Refresh/poll admin item until `done` or `failed`. Disable repeated clicks while pending. Errors 401/403/404, 409 `ai_already_done`, 422 invalid ID. A 202 means queued, not completed.

### GET `/api/admin/items/{item_id}/photos/{photo_id}`

Returns **JPEG bytes**, `Content-Type: image/jpeg`, not JSON or a public URL. Requires the admin cookie even in an image tag. `photo_id` must belong to `item_id`.

```html
<!-- With a same-origin /api proxy, the browser sends the cookie. -->
<img src="/api/admin/items/1/photos/7" alt="Found item" />
```

Errors 401/403/404/422. Uploaded PNG/WebP files are re-encoded as JPEG. Photos have no owner-facing endpoint.

### GET `/api/admin/claims`

Optional `status`, default **`in_review`**. Example: `?status=approved`. To list all statuses, send **`?status=`** (empty value); omitting the parameter uses the review default. Returns **200 AdminClaim[]**, newest first. Use known statuses only. No pagination.

### GET `/api/admin/claims/{claim_id}`

Returns **200 AdminClaim** with evidence, score and private item attributes. Errors 401/403/404/422.

### POST `/api/admin/claims/{claim_id}/decision`

JSON: `{"decision":"approve","note":"Reviewed ownership evidence."}`.

`decision` is required, `approve|reject`. `note` is optional, max 500 or null. Only an `in_review` claim can be decided. Returns **200 Claim** without a pickup code. Approval reserves the item and rejects competing review claims; then the owner requests their code. Errors 401/403/404/422, 409 `not_in_review`, `item_unavailable`, or `item_not_in_locker`.

### GET `/api/admin/audit`

| Query | Type | Default/rule |
|---|---|---|
| `limit` | Integer | 100; range 1–1000. |
| `entity_type` | String | Optional; exact match, e.g. `found_item`, `claim`, `locker`. |
| `entity_id` | Integer | Optional; combine with type to avoid unrelated entities sharing an ID. |

Example: `/api/admin/audit?limit=100&entity_type=found_item&entity_id=1`.

Returns **200 AuditEntry[]**, newest first. There is no `/api/admin/audit-log` route or `only_alerts` filter in this backend. Errors 401/403/422.

## 9. Response models

Models not already expanded above:

### AdminItem

```json
{
  "id":1, "locker_id":1, "compartment":1, "location":"library",
  "note":"Black Samsung phone, cat sticker, serial ends 4821", "finder_contact":null,
  "status":"open", "found_at":"2026-11-11T08:00:00",
  "ai_status":"done", "ai_attempts":1, "ai_error":null, "category":"phone",
  "public_summary":"Black Samsung phone",
  "description":"Black Samsung phone, cat sticker, serial ends 4821",
  "attributes":[
    {"name":"color","value":"black","visibility":"public","strength":"generic","confidence":0.7},
    {"name":"serial_suffix","value":"4821","visibility":"private","strength":"strong","confidence":0.9}
  ],
  "photo_ids":[7]
}
```

`id`, `ai_attempts`, `photo_ids[]` are numbers. `locker_id` and `compartment` are number|null; `note`, `finder_contact`, `ai_error`, `category`, `public_summary`, `description` are string|null. Other strings are non-null. `attributes` is Attribute[]; its strength/confidence are nullable in the schema. Historical returned items can retain their compartment number; it is not a promise that they are still physically inside.

### AdminClaim

```json
{
  "id":3, "user_id":1, "found_item_id":1, "lost_report_id":2,
  "status":"in_review", "ownership_score":60, "critical_conflict":false,
  "created_at":"2026-11-11T08:10:00", "decision_note":null,
  "evidence":[{"type":"serial_suffix","value":"4821","result":"match","similarity":1.0}],
  "item_summary":"Black Samsung phone",
  "item_private_attributes":[{"name":"serial_suffix","value":"4821","visibility":"private","strength":"strong","confidence":0.9}]
}
```

`ownership_score` is number|null, `decision_note`/`item_summary` string|null. Evidence has `type`, `value`, `result` strings and `similarity` number|null. Stored results are `match|mismatch|not_verifiable`; a critical mismatch is represented by `mismatch` plus the claim's `critical_conflict` flag. Scores/evidence are admin-only and are not included in owner Claim responses.

### AuditEntry

```json
{
  "id":10, "at":"2026-11-11T08:10:00", "actor_type":"user", "actor_id":1,
  "action":"claim_submitted", "entity_type":"claim", "entity_id":3,
  "details":{"decision":"approved","score":100,"conflict":false}
}
```

`actor_id`, `entity_id` are number|null; `details` is an object|null with action-specific keys. Render unknown keys gracefully; do not hardcode one details shape for every action. Actor types include `user`, `admin`, `finder`, `device`, `system`.

## 10. Device APIs and simulation

These endpoints are documented for completeness and backend testing. The frontend shows issued codes but does not authenticate as a locker. Keep `X-Device-Key` out of shipped JavaScript. Use a separate test tool to simulate the ESP32.

All device endpoints require `X-Device-Key: <the seeded key>`. This is separate from browser login. Missing/wrong key returns 401 `invalid_device_key`. For code/state requests, `device_id` must match that key's locker.

### POST `/api/device/codes/validate`

```json
{"device_id":"locker_01","code":"004821"}
```

Required device ID string 1–50; code exactly six digits as a string. Returns **200 CodeResult**:

```json
{"authorized":true,"compartment":1,"action":"deposit"}
```

`action` is `deposit|pickup`. Denial is also HTTP 200:

```json
{"authorized":false,"compartment":null,"action":null}
```

Check `authorized`, not only `response.ok`. Codes are consumed on successful validation; validating one just to “check” it will use it. Invalid/expired/already-used/rate-limited codes are denied without a detailed reason. Errors: 401, 422. `POST /locker/validate` is an exact legacy alias with the same auth/body/response.

### POST `/api/device/compartments/{number}/state`

JSON: `{"device_id":"locker_01","occupied":true}`. Device ID string 1–50 and boolean `occupied` are required. `number` is the compartment number **within the device**, not a database primary key. Prototype uses 1.

Returns **200 `{"compartment":1,"state":"occupied"}`**. After a validated deposit code, `occupied:true` marks the item stored. After a validated pickup code, `occupied:false` marks it returned, resolves the report, and frees the compartment. Sending occupancy without an appropriate preceding open transition does not force a transition. Errors 401/404/422.

### POST `/api/device/heartbeat`

JSON body `{}` or `{"firmware_version":"1.0"}`. `firmware_version` optional string|null. A JSON object body is still required. Returns **200 `{"ok":true,"server_time":"2026-11-11T08:00:00"}`**. It updates last-seen time; firmware version is currently not persisted. Errors 401/422.

## 11. Frontend workflows

### Finder screen

1. Read `locker_code` (e.g. `L1`) from the page URL agreed by the frontend team.
2. GET locker info; render availability and the location options.
3. Validate 1–3 supported photos, then submit the multipart deposit **once**.
4. Show the returned compartment, deposit code and expiry, with “Enter this code on the locker; after placing the item and closing it, press #”.
5. Do not describe the item as stored solely because POST returned 201. There is no finder progress endpoint.

The proposed `/found/new?locker=L1` is a **frontend route**, not an implemented backend page endpoint.

### Owner screens

1. GET `/api/auth/me`, or register/login.
2. POST lost report and keep its `id`.
3. GET its candidates. Show an empty state if `[]`; allow manual refresh.
4. Select `found_item_id`; collect private evidence; POST claim with **both** report/item IDs.
5. Branch on claim `status`: approved → show returned code; review → waiting view; rejected → generic failure message.
6. After admin approval, request the pickup code explicitly. GET claim does not reveal it.
7. Show the code as text with leading zeroes, compartment and countdown. A refresh loses an unpersisted code; let the owner request a replacement.
8. After physical pickup, GET the lost report to detect `resolved`.

### Admin screens

1. Login as the seeded admin; `GET /api/auth/me` confirms `role:admin`.
2. Item list/details: use item/AI filters; images use authenticated photo paths.
3. Edit the full attribute list, or retry failed extraction; refresh details afterward.
4. Review queue defaults to `in_review`. Display evidence and private attributes only here.
5. Submit approve/reject, then refresh the queue. A competing admin/owner may already have changed it; handle 409.
6. Audit screen displays the newest array and optional entity filters.

### Loading and retry behavior

- Disable submit buttons while pending. No idempotency key is implemented for deposit/report/claim submissions.
- Show separate states for “loading”, `[]`, business rejection, network failure, and server error.
- Do not repeatedly request pickup codes or AI retry actions in a render effect.
- No WebSocket/SSE/notification endpoint exists. Poll only read endpoints as needed and stop timers when leaving the screen.
- Login/account errors should clear cached private data; a 403 is an authorization problem, not a reason to retry indefinitely.

## 12. Vocabularies and states

### Input values

| Field | Accepted values |
|---|---|
| Category | `phone`, `wallet`, `keys`, `bag`, `laptop`, `tablet`, `headphones`, `bottle`, `umbrella`, `clothing`, `id_card`, `glasses`, `book`, `jewelry`, `other` |
| Color | `black`, `white`, `gray`, `silver`, `gold`, `red`, `orange`, `yellow`, `green`, `blue`, `purple`, `pink`, `brown`, `beige`, `multicolor` |
| Evidence type | `serial_suffix`, `model`, `sticker_or_mark`, `damage`, `contents`, `accessory`, `engraving`, `other` |
| Attribute visibility | `public`, `private` |
| Attribute strength | `generic`, `distinctive`, `strong` |
| Default locations | `library`, `student_center`, `engineering_building`, `lecture_hall`, `cafeteria`, `gym`, `dormitory`, `outdoor`, `other` |

Locations are configurable; GET locker info is authoritative. Categories/colors/evidence types are fixed by the current schemas. Use `headphones`, not `earphones`; `id_card`, not `card`; `gray`, not `grey`. Human labels can be translated without changing request values.

### Lowercase state values

| Entity | Values / meaning |
|---|---|
| Found item | `awaiting_deposit` → `open` (stored) → `reserved` → `returned`; `expired` for cancelled/unused deposits. |
| AI | `pending`, `done`, `failed`; independent of physical item state. |
| Lost report | `open`, `resolved` after confirmed pickup, `closed` (schema supports it; no close API). |
| Claim | `pending`, `approved`, `in_review`, `rejected`; normal POST immediately returns one of the last three. |
| Compartment | `free`, `deposit_reserved`, `deposit_open`, `occupied`, `pickup_reserved`, `pickup_open`. |

Do not send old uppercase values or invent `stored`, `collected`, `out_of_service` filters. Default verification uses approve threshold 80, review threshold 50; critical conflict rejects. Generic categories (`umbrella`, `bottle`, `clothing`, `book`) and generic evidence sets go to admin review instead of auto-approval. The frontend displays the server decision rather than reproducing this policy.

## 13. Testing and unsupported features

### Manual test scenario

Start Docker with `docker compose up --build`. Default admin is `admin@example.com` / `changeme123`. Default locker is `L1`, device is `locker_01`, compartment 1. Save the device key from the **first-start backend logs** for a separate device test client. Never put it into frontend source.

1. Register a new owner and retain its browser/session cookie.
2. Anonymous deposit with a real small JPEG/PNG and note `Black Samsung phone, cat sticker, serial ends 4821`.
3. In the device test tool, validate the **returned** deposit code, then report `occupied:true`.
4. Create a phone report for library, black/Samsung, a recent UTC lost time, and description `Black Samsung phone with a cat sticker`.
5. GET candidates; select the actual returned `found_item_id`.
6. Submit the two evidence values shown in section 7. With the default mock, this produces approval and a pickup code.
7. Validate that pickup code in the device tool, then report `occupied:false`.
8. Confirm the owner's report is resolved and locker free count is 1.

With mock AI, extraction reads the **finder note**, not image content. Uploading a phone photo without the example details does not generate the same mock evidence. Photo upload still validates real image bytes. For review testing, submit only serial evidence or use a generic category, then login as admin in a separate browser profile/test client to decide it.

### Postman usage

Import `postman-collection.json`, set `base_url`, choose a photo in the deposit request, and set `device_key` only in the test tool. Cookies are automatic after login. Deposit/report/claim responses capture IDs and codes into collection variables. To use admin requests, login with the seeded admin credentials; use separate collection copies/cookie jars if testing owner and admin simultaneously. For pickup, replace `{{deposit_code}}` with `{{pickup_code}}` in device validation, then set occupancy to false. Choose the photo ID from AdminItem when requesting an image. This is a manual collection, not a ready-to-run unattended scenario.

### Not implemented; do not build UI calls to these

- No `POST /api/deposit-sessions` finder-token flow.
- No general locker list, public found-item list/details, owner/finder photo access, or finder deposit-status endpoint.
- No report/claim edit, delete, cancel or manual report-close endpoints.
- No password reset, email verification, account editing or public admin registration.
- No search parameters, pagination (except audit `limit`), WebSocket/SSE, email/SMS notifications, or code-recovery GET.
- No browser-side device control, implemented frontend page routes, or cross-origin CORS configuration.
- No guaranteed uniform JSON for unexpected 500/proxy errors, no retry timing metadata, no idempotency support.

The full mock-AI API workflow and restart persistence were tested over real HTTP with Docker/MySQL 8.4 on 2026-11-11. Real Claude responses and the physical ESP32 still need their own integration runs.
