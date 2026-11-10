# PrivateFind — REST API Contract (v1 draft)

WBS 4.2 · Updated 2026-11-10: Simon database + Raphael device contract. The running backend is the live reference: open `http://localhost:8000/docs`.

## Conventions
- **Encoding:** JSON in, JSON out. The only exception is `POST /api/deposits`, which is `multipart/form-data` because of the photos.
- **Times:** ISO 8601, UTC (`2026-10-14T09:30:00`).
- **Errors** always have the same shape, with the HTTP status set accordingly:
  ```json
  { "error": { "code": "compartment_unavailable", "message": "No free compartment in this locker." } }
  ```
  Common codes:
  - `validation_error` (422)
  - `not_authenticated` (401)
  - `forbidden` (403)
  - `not_found` (404)
  - `conflict` (409)
  - `rate_limited` (429)
- **Browser auth:** session cookie set by `/api/auth/login` or `/api/auth/register` (HttpOnly, SameSite=Lax). The JS must send it with `fetch(url, {credentials: "same-origin"})`.
- **Device auth:** header `X-Device-Key: <locker key>` on every `/api/device/*` request.
- **Roles:** `owner` (any registered user) and `admin`. Finders are anonymous.

### Fixed vocabularies
| Name | Values |
|---|---|
| category | `phone, wallet, keys, bag, laptop, tablet, headphones, bottle, umbrella, clothing, id_card, glasses, book, jewelry, other` |
| color | `black, white, gray, silver, gold, red, orange, yellow, green, blue, purple, pink, brown, beige, multicolor` |
| location | configured list, default `library, student_center, engineering_building, lecture_hall, cafeteria, gym, dormitory, outdoor, other` |
| evidence / private attribute type | `serial_suffix, model, sticker_or_mark, damage, contents, accessory, engraving, other` |

---

## 1. Auth (`identity`)
| Method | Path | Body | Success |
|---|---|---|---|
| POST | `/api/auth/register` | `{email, password (min 8), display_name?}` | 201 `User`, logged in |
| POST | `/api/auth/login` | `{email, password}` | 200 `User` |
| POST | `/api/auth/logout` | — | 204 |
| GET | `/api/auth/me` | — | 200 `User` |

`User = {id, email, display_name, role}`

## 2. Finder deposit (`found_items`, `locker`), public
| Method | Path | Body | Success |
|---|---|---|---|
| GET | `/api/lockers/{locker_code}` | — | 200 `{code, name, location, free_compartments, locations: [...]}` |
| POST | `/api/deposits` | multipart: `locker_code`, `location`, `note?` (≤ 500, defaults to empty), `photos` (1–3 files, jpeg/png/webp, ≤ 5 MB each), `finder_contact?` | 201 `{item_id, compartment, deposit_code, expires_at}` |

- `409 compartment_unavailable` if the locker is full.
- `429 rate_limited` after 5 deposits per 10 min from one IP.
- AI extraction starts in the background; the response never waits for it.

## 3. Lost reports and candidates (`lost_reports`, `matching`), owner
| Method | Path | Body | Success |
|---|---|---|---|
| POST | `/api/lost-reports` | `{category, location, lost_at, color?, brand?, model?, description}` | 201 `LostReport` |
| GET | `/api/lost-reports` | — | 200 `[LostReport]` (mine) |
| GET | `/api/lost-reports/{id}` | — | 200 `LostReport` |
| GET | `/api/lost-reports/{id}/candidates` | — | 200 `[Candidate]` (≤ 3, score ≥ 60) |

`Candidate = {found_item_id, score, breakdown: {category, location, time, attributes, semantic}, category, color, location, found_date, public_summary}`

- Only public data is returned. No photos, no private attributes.

## 4. Claims (`claims`), owner
| Method | Path | Body | Success |
|---|---|---|---|
| POST | `/api/claims` | `{lost_report_id, found_item_id, evidence: [{type, value}] (1–8)}` | 201 `Claim` |
| GET | `/api/claims` | — | 200 `[Claim]` (mine) |
| GET | `/api/claims/{id}` | — | 200 `Claim` |
| POST | `/api/claims/{id}/pickup-code` | — | 200 `{compartment, pickup_code, expires_at}` (approved claims only; replaces any older code) |

`Claim = {id, found_item_id, lost_report_id, status: pending|approved|in_review|rejected, message, created_at, pickup_code?, pickup_expires_at?, compartment?}`

- `pickup_code` appears **only** in the response that approves the claim. Afterwards, use `/pickup-code` to get a new one.
- The item must be one of the report's candidates (`409 not_a_candidate` otherwise).
- After 3 rejected claims on the same item, the user gets `429 claim_cooldown` for 24 h.
- `message` never says which detail was wrong.

## 5. Admin (`role = admin`)
| Method | Path | Body | Success |
|---|---|---|---|
| GET | `/api/admin/claims?status=in_review` | — | `[AdminClaim]` (with evidence, score, item private attributes) |
| GET | `/api/admin/claims/{id}` | — | `AdminClaim` |
| POST | `/api/admin/claims/{id}/decision` | `{decision: approve\|reject, note?}` | `Claim` |
| GET | `/api/admin/items?status=&ai_status=` | — | `[AdminItem]` |
| GET | `/api/admin/items/{id}` | — | `AdminItem` (all attributes, finder contact, photo ids) |
| PUT | `/api/admin/items/{id}/attributes` | `{category, attributes: [{name, value, visibility, strength}]}` | `AdminItem` |
| POST | `/api/admin/items/{id}/retry-ai` | — | 202 |
| GET | `/api/admin/items/{id}/photos/{photo_id}` | — | image file |
| GET | `/api/admin/audit?limit=100&entity_type=&entity_id=` | — | `[AuditEntry]` |

## 6. Locker device (`locker`, header `X-Device-Key`)
| Method | Path | Body | Success |
|---|---|---|---|
| POST | `/api/device/codes/validate` | `{device_id, code}` | 200 `{authorized: true, compartment, action: "deposit" or "pickup"}` or `{authorized: false, compartment: null, action: null}` |
| POST | `/api/device/compartments/{no}/state` | `{device_id, occupied: bool}` (sent after `#`) | 200 `{compartment, state}` |
| POST | `/api/device/heartbeat` | `{firmware_version?}` | 200 `{ok, server_time}` |

- Device ID `locker_01` must match the key's locker. Codes have six digits.
- Wrong key/device ID gives 401; invalid, expired, used or throttled codes give `authorized: false`.
- The prototype seed creates one compartment, matching the physical locker.
- Configure firmware URLs to these existing paths. No response-parser changes are needed.
- `/locker/validate` is also accepted as an alias for code validation, matching the older firmware example URL.

### Stored states (Simon schema)
`free → deposit_reserved → deposit_open → occupied → pickup_reserved → pickup_open → free`

- `deposit_open` + empty → `free`; found item becomes `expired`.
- An expired deposit code releases `deposit_reserved` back to `free`.
- `pickup_open` + still occupied → `occupied`; issue a new pickup code.
- Expired pickup codes can be replaced while the compartment is `pickup_reserved`.
- Found items: `awaiting_deposit → open → reserved → returned` (or `expired`).
- AI: `pending → done | failed`. Claims: `pending | approved | in_review | rejected`.
- Lost reports: `open → resolved` on confirmed pickup (`closed` is available for a manually closed report).

The browser payload names above remain stable; stored enum values now use Simon's lowercase values.
See [team integration](team-integration.md) for database setup and the fields added for this backend.
