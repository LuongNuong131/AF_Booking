# API contract — Prompt 1B

This document records the user's shared contract for all implementation prompts. Paths, JSON field names, and error codes must not change silently. Update this file and the wire models together if an approved change is needed.

**Implementation status:** probes/auth and Prompt 4 booking lookup, notes, lists, status catalogue, notifications, and Admin/QC supplier-folder edits are implemented. Attachments intentionally return 501 through NullStorage. Prompt 4B additionally implements search, folder lists/detail, station autocomplete and Admin station naming. Prompt 5 implements WebSocket updates/soft locks/private notifications/session logout and stale reminder jobs. Prompt 7B adds private task mutations, due jobs/events and profile reminder preferences. Prompt 7C adds folder stale counts and the smart folder UI. Prompt 8D implements watch, assignments, the rate-limited active-user directory and collaboration UI. Prompt 8E operations/daily reports/note search/PWA push and Prompt 8F invoice management/reconciliation are also implemented. Later-prompt endpoints remain reserved.

## Common conventions

- Business HTTP and WebSocket paths use `/api/v1`; the table omits that prefix. Prompt 3 also exposes the public process probe at `/health`, preserving `/api/v1/health` as an alias.
- JSON keys use `snake_case`. Output timestamps are UTC ISO 8601 strings with milliseconds, such as `2026-11-02T08:15:30.123Z`. Naive timestamps are rejected by the shared models; aware timestamps are normalized to UTC on serialization.
- Page pagination: `{items, total, page, size}`. Pages are one-based. Cursor pagination: `{items, next_cursor}`; `next_cursor` is explicitly `null` at the end. Cursors are opaque to the frontend.
- Errors always use `{code, message, details?}` at the top level. Do not wrap them in `error` or FastAPI's default `detail`. Messages are English; clients branch on `code`, not message text.
- Any object containing `booking_key` also contains `display_key`, including nested objects. Requests, comparisons, URLs, caches, and WebSocket identities use the canonical key; UI uses the display key. A key such as `CW2154654-RDU-2609` displays as `CW 2154654-RDU-2609`.
- In FastAPI, declare `/bookings/mine`, `/bookings/stale`, and `/bookings/lookup` before `/bookings/{key}`. Apply the same fixed-path-before-parameter rule to other groups.
- Authenticated means a valid active session. Admin/QC checks and ownership checks belong on the backend. Other users' tasks return 404, not 403. Notifications are private to their owner.

## Wire types

Executable field definitions are in [`backend/app/schemas/contracts.py`](../backend/app/schemas/contracts.py) [`backend/app/schemas/auth.py`](../backend/app/schemas/auth.py), and [`backend/app/schemas/bookings.py`](../backend/app/schemas/bookings.py), and [`backend/app/schemas/folders.py`](../backend/app/schemas/folders.py). Frontend equivalents are generated in [`frontend/src/types/api.generated.ts`](../frontend/src/types/api.generated.ts); do not edit that file manually.

| Type | Fields |
| --- | --- |
| `BookingSnapshot` | `booking_key`, `display_key`, `cw_number`, `station_code`, `period`, `period_label`, `supplier:{name,type}`, `version`, `last_status:{code,label}\|null`, `last_position\|null`, `last_agent:{id,full_name}\|null`, `last_note_preview\|null`, `is_done`, `done_at\|null`, `updated_at`, `is_stale`, `invoice_state`, `invoice_count`, `invoices_preview` (at most 3 strings) |
| `Invoice` | `id`, `invoice_number`, `added_by:{id,full_name}`, `created_at` |
| `InvoiceChange` | optional `add:string[]`, `remove_ids:number[]`, `no_invoice:boolean` |
| `Note` | `id`, `agent:{id,full_name}`, `status:{code,label}`, `position`, `note\|null`, `created_at`, `attachments:[{id,file_name,mime_type,size_bytes}]`, `invoice_change:{added:string[],removed:string[],no_invoice:boolean\|null}\|null` |
| `Status` | `id`, `code`, `label`, `position_label`, `note_required`, `is_done`, `sort_order`, `suggest_task`, `default_task_days`, `invoice_required` |
| `Task` | `id`, `booking_key`, `display_key`, `message`, `remind_at`, `status`, `is_due`, `is_overdue`, `snooze_count`, `created_at`, `completed_at\|null`, `booking_changed_since`, `booking:{last_status,last_agent,is_done,updated_at}` |
| `Suggestion` | `booking_key`, `display_key`, `last_status`, `last_agent`, `updated_at`, `distance` |
| `FolderCard` | `cw_number`, `supplier_name`, `supplier_type`, `station_code`, `booking_count`, `open_count`, `stale_count` (additive, default 0), `last_activity_at`, `latest:{booking_key,display_key,period_label,status,agent}\|null` |
| `MonthRow` | `booking_key`, `display_key`, `period`, `period_label`, `last_status`, `last_position`, `last_agent`, `is_done`, `is_stale`, `updated_at`, `invoice_state`, `invoice_count` |
| `KeyResolution` | `status`, `input_kind`, `key\|null`, `display_key\|null`, optional `candidates:[{key,display_key,station_code,supplier_name}]` |

Unions:

- `supplier.type` / `supplier_type`: `hotel | transportation`.
- `invoice_state`: `unknown | has_invoice | no_invoice`.
- Task `status`: `pending | done | cancelled`.
- Resolution `status`: `exact | resolved_from_partial | needs_station | ambiguous | invalid`.
- Resolution `input_kind`: `full | partial | invalid`.
- Search `kind`: `booking | partial_key | folder | folders | station | station_period | invoice | none`.
- `notifications.type`: `taken_over | stale | task_due | watch_update | assigned | assignment_done`.

Nested `status`/`last_status` values use `{code,label}|null`, and agent summaries use `{id,full_name}|null` where the parent can lack a latest note. Status codes remain strings backed by the dynamic database catalogue, not a fixed enum. A period is a string such as `2608`; its label is `Aug 2026`. IDs are JSON integers; database design must keep them in JavaScript's safe integer range or explicitly revise the contract.

Nullable fields are present as `null`; optional fields may be omitted. Request handlers must use Pydantic's `model_fields_set` / `model_dump(exclude_unset=True)` when distinguishing an omitted `InvoiceChange` field from an explicit `false`. Shared DTOs do not implement business validation, authorization, or persistence.

Regenerate/check frontend types from the checkout root:

```sh
backend/.venv/bin/python scripts/generate_contract_types.py
backend/.venv/bin/python scripts/generate_contract_types.py --check
```

CI checks that the generated file is current and runs the frontend build.

## Errors

### Authenticated booking creation

`POST /bookings` is available to Agent, QC, and Admin. It accepts a
`BookingCreateRequest`:

```json
{
  "booking_key": "CW2154654-RDU-2609",
  "supplier_name": "Example Hotel",
  "supplier_type": "hotel",
  "confirm_new": false
}
```

`booking_key` is required and bounded to 100 characters; its normalized full key
is validated and stored canonically. Supplier fields are optional for an existing
CW/station folder and required for a new one. A new folder requires a cleaned
supplier name of 3–255 characters and `hotel | transportation`; an existing
folder's metadata is never changed by this request. Unknown fields are rejected.

Success is `201` with a `BookingItem` at version `1`, nullable latest-note fields,
`invoice_state: "unknown"`, and zero invoices. Creation writes no note and does
not assign ownership. The returned version must be used for the first note.
The existing `booking.updated` event is sent after commit with null agent/status
fields. No additional realtime event format is introduced.

Relevant errors are `401 UNAUTHORIZED`, `422 INVALID_BOOKING_KEY`,
`422 STATION_REQUIRED`, `422 SUPPLIER_REQUIRED`, and
`422 NEW_BOOKING_NEEDS_CONFIRM` (existing suggestion envelope). `confirm_new`
acknowledges similar numbers only. An exact normalized duplicate always returns
`409 BOOKING_EXISTS` with details `{booking_key, display_key}`, including races
between users and bookings with no live notes. Uncertain creation requests may
be safely retried: a committed booking returns `BOOKING_EXISTS`, after which the
client can open the existing booking. Creation never overwrites an existing row.

### Auth implementation details — Prompt 3

- `POST /auth/login` accepts JSON `{username,password}`. Success returns `{access_token,user,token_type:"bearer",expires_in}`; the last two fields are explicit additions for bearer-token clients. `expires_in` is seconds (default 43200).
- `user` and the direct `GET /auth/me` result contain `id`, `username`, `full_name`, `role`, `is_active`, `must_change_password`, and `settings` (JSON or null). They never include `password_hash` or `current_session_id`.
- `POST /auth/logout` returns `{message:"Signed out."}` and revokes the current SID.
- `POST /auth/change-password` accepts `{old_password,new_password}`. Success returns `{message:"Password changed. Please sign in again."}` and revokes the session. The client must sign in again. A wrong old password or invalid new password is `422 VALIDATION_ERROR`. New passwords have 10–128 characters.
- Authenticated requests use `Authorization: Bearer ...`. JWTs require valid HS256 signatures, issuer/audience, expiration, user ID, role, and UUID SID. Invalid/expired tokens and inactive/deleted users return `401 UNAUTHORIZED`; an active user's replaced/cleared SID returns `401 SESSION_REPLACED`. Permissions use the current user role, not a stale JWT role alone.
- The first five invalid credential attempts return 401; later attempts in the lockout return `429 RATE_LIMITED` with `Retry-After`. Cache/session invalidation and in-memory scope are documented in [auth.md](auth.md).
- Every HTTP response has `X-Request-ID`; browser CORS exposes it and `Retry-After`. Auth responses use `Cache-Control: no-store`.

No registration, refresh-token, booking, or admin-management endpoint is added in Prompt 3. Prompt 5 now implements that internal callback through the real WebSocket manager and defines its wire frame in ws-protocol.md.

| Code | HTTP | Details / behavior |
| --- | --- | --- |
| `PASSWORD_CHANGE_REQUIRED` | 403 | Temporary password must be changed before business access |
| `PAYLOAD_TOO_LARGE` | 413 | Request body exceeds 1 MB |
| `UNAUTHORIZED` | 401 | No valid authenticated session |
| `SESSION_REPLACED` | 401 | A newer login replaced this session |
| `FORBIDDEN` | 403 | Insufficient permission |
| `NOT_FOUND` | 404 | Missing resource; also another user's task |
| `VALIDATION_ERROR` | 422 | Request validation failed; sanitized `details.errors` contains `loc` and `type` only |
| `NOTE_REQUIRED` | 422 | Selected status requires note text |
| `STATUS_INACTIVE` | 422 | Selected status is inactive |
| `TASK_LIMIT_REACHED` | 422 | Pending-task limit exceeded |
| `NEW_BOOKING_NEEDS_CONFIRM` | 422 | `details.suggestions: Suggestion[]` |
| `DUPLICATE_RECENT_NOTE` | 409 | `details.note: Note` is the previous matching note |
| `WATCH_LIMIT_REACHED` | 422 | Watch limit exceeded |
| `ASSIGNMENT_INVALID` | 422 | Invalid assignment |
| `INVALID_BOOKING_KEY` | 422 | Invalid key for new booking creation |
| `STATION_REQUIRED` | 422 | `details.suggested_key` when a folder supplies the station |
| `STATION_MISMATCH` | 422 | `details.expected_station` and `details.suggested_key` |
| `SUPPLIER_REQUIRED` | 422 | A new CW requires supplier name/type |
| `VERSION_CONFLICT` | 409 | `details` is the latest `BookingSnapshot`, including nullable fields |
| `INVOICE_REQUIRED` | 422 | Required invoice declaration is unknown |
| `INVOICE_INVALID` | 422 | `details.invalid: string[]` |
| `INVOICE_STATE_CONFLICT` | 422 | Conflicting invoice numbers and no-invoice state |
| `INVOICE_LIMIT_REACHED` | 422 | Invoice limit exceeded |
| `RATE_LIMITED` | 429 | Request rate exceeded |
| `REQUEST_TIMEOUT` | 504 | Backend request deadline elapsed |
| `SERVICE_BUSY` | 503 | Include a `Retry-After` header |
| `INTERNAL` | 500 | Safe generic message; no exception/SQL/credential details |

Examples:

```json
{"code":"REQUEST_TIMEOUT","message":"This is taking too long. Please try again."}
```

```json
{"code":"STATION_REQUIRED","message":"This booking number has no station code. Enter the station (3 letters) to continue.","details":{"suggested_key":"CW2154654-RDU-2609"}}
```

### Compatibility changes and explicit clarifications

- The foundation's `{"error":{...}}` timeout wrapper is removed. Clients now read `code` and `message` directly.
- Existing public infrastructure probes `/health` and `/ready` remain in addition to the requested future `/health/warm` and protected `/admin/system/health`. They are different endpoints with different purposes.
- `/ready` success remains `200 {status:"ok",database:"connected"}`. Failure now uses `503 {code:"SERVICE_BUSY",message,details:{database:"not_configured"|"unavailable"}}` with `Retry-After: 5`. The frontend has been updated together.
- Rejected CORS preflights now return JSON `FORBIDDEN` with 403 instead of the framework's plain-text 400. Successful preflight responses remain HTTP protocol responses.
- Framework HTTP statuses not listed in the business catalogue (for example method-not-allowed 405) retain their HTTP status and use the same error envelope with `VALIDATION_ERROR`; their headers, such as `Allow`, are preserved. The specified business-code/status pairs above do not change.
- `Task.display_key` and `FolderCard.latest.display_key` are explicit additions required by the universal booking-key/display-key rule, although omitted in the shorthand examples in Prompt 1B.
- Unspecified shorthand types are resolved as strings for position labels, nullable status/agent summaries for incomplete snapshots, nullable `Status.default_task_days`, and a numeric user ID for `assign_to`. Error payloads without explicit field names use `details.suggestions` and `details.note` as shown above.
- Prompt 1B reserved the event names below. Prompt 5 now defines `{event,data}` and exact implemented payloads in [ws-protocol.md](ws-protocol.md); `task.due` is now implemented by Prompt 7B, including the missing Prompt 5B prerequisite.

## Endpoint catalogue

Prompt 2 storage includes this contract's invoice fields/table, status task/invoice settings, and all six notification types; see [database-schema.md](database-schema.md). It adds no business HTTP handlers and changes no wire field names above.

`Authenticated` means any valid logged-in role. All paths below include the common `/api/v1` prefix at runtime. Defaults shown for pagination must be preserved when handlers are added.

| Group | Method + path | Access | Contract |
| --- | --- | --- | --- |
| Auth | `POST /auth/login` | Public | Return `access_token`, `user` |
| Auth | `POST /auth/logout` | Authenticated | End session |
| Auth | `GET /auth/me` | Authenticated | Current user |
| Auth | `POST /auth/change-password` | Authenticated | Change password |
| Booking | `GET /bookings/lookup?key=` | Authenticated | Accept every input form from Prompt 1 §4.1b/c. Return `resolution:KeyResolution`, `display_key`, snapshot, supplier/group (`group`, `group_exists`), warnings, `suggestions` for missing bookings, `my_tasks`, and first history page |
| Booking | `GET /bookings/mine?page&size=10` | Authenticated | Filter `last_agent_id` to current user |
| Booking | `GET /bookings?page&size=20&q&status_code&agent_id&is_done&stale&invoice_state&invoice&date_from&date_to&sort` | Authenticated | Overall list |
| Booking | `GET /bookings/stale?scope=mine\|all&page&size` | Authenticated | Stale bookings |
| Booking | `GET /bookings/{key}` | Authenticated | Snapshot and first history page |
| Booking | `GET /bookings/{key}/notes?cursor&limit` | Authenticated | Cursor-paginated history |
| Booking | `POST /bookings/{key}/notes` | Authenticated | See note-save body below; canonical full key required |
| Catalogue | `GET /statuses` | Authenticated | Active statuses only |
| Task | `POST /bookings/{key}/tasks` | Authenticated | Body `remind_date, remind_time?, message?, client_request_id?` |
| Task | `GET /bookings/{key}/tasks` | Authenticated | Current user's pending tasks only |
| Task | `GET /tasks?view=pending\|due\|done&page&size=10` | Authenticated | Current user's tasks only |
| Task | `GET /tasks/due` | Authenticated | Current user's due tasks |
| Task | `PATCH /tasks/{id}` | Owner | Edit task |
| Task | `POST /tasks/{id}/complete` | Owner | Complete task |
| Task | `POST /tasks/{id}/snooze` | Owner | Snooze task |
| Task | `DELETE /tasks/{id}` | Owner | Cancel task |
| Notification | `GET /notifications?limit` | Authenticated | Own notifications |
| Notification | `POST /notifications/{id}/read` | Owner | Mark read |
| Notification | `POST /notifications/read-all` | Authenticated | Mark own notifications read |
| Profile | `PATCH /profile`, `GET /profile/stats` | Authenticated | Own profile/statistics |
| Report | `GET /reports/performance` | Admin, QC | Performance report |
| Export | `GET /export/daily` | Admin, QC | Daily record export |
| Admin | `GET /admin/users`, `POST /admin/users`, `PATCH /admin/users/{id}` | Admin | User management |
| Admin | `POST /admin/users/{id}/reset-password`, `POST /admin/users/{id}/kick` | Admin | Password reset/session eviction |
| Admin | `GET /admin/audit`, `GET /admin/trash` | Admin | Audit and trash |
| Admin | `DELETE /admin/notes/{id}`, `POST /admin/notes/{id}/restore` | Admin | Soft delete/restore |
| Admin | `GET /admin/statuses`, `POST /admin/statuses`, `PATCH /admin/statuses` | Admin | No hard deletion; preserve the specified PATCH path |
| Search | `GET /search?q&page&size=20` | Authenticated | Search kinds listed above; Prompt 4B |
| Folder | `GET /folders/{cw}` | Authenticated | CW folder; Prompt 4B |
| Folder | `GET /folders?page&size=20&station_code&supplier_type&q` | Authenticated | Folder list; Prompt 4B |
| Folder | `PATCH /folders/{cw}` | Admin, QC | Edit `supplier_name`, `supplier_type`; Prompt 4B |
| Station | `GET /stations?q` | Authenticated | Station lookup; Prompt 4B |
| Station | `PATCH /admin/stations/{code}` | Admin | Station administration; Prompt 4B |
| Watch | `PUT /bookings/{key}/watch`, `DELETE /bookings/{key}/watch` | Authenticated | Watch/unwatch; Prompt 8D |
| Watch | `GET /watching?page&size=10` | Authenticated | Own watched bookings; Prompt 8D |
| Assignment | `GET /users/lookup?q` | Authenticated | Assignee lookup; Prompt 8D |
| Assignment | `GET /assignments?view=to_me\|from_me&status&page&size=10` | Authenticated | Assignment list; Prompt 8D |
| Assignment | `POST /assignments/{id}/complete`, `POST /assignments/{id}/decline` | Authenticated | Ownership rules in Prompt 8D; create through note-save body |
| Integrity | `GET /admin/integrity`, `POST /admin/integrity/run`, `POST /admin/integrity/fix` | Admin | Prompt 8C |
| System health | `GET /admin/system/health` | Admin | Prompt 8E; not the public infrastructure probe |
| Daily report | `GET /reports/daily?date=`, `GET /reports/daily/export?date=` | Admin, QC | Prompt 8E |
| Note search | `GET /search/notes?q&agent_id&status_code&date_from&date_to&page&size=20` | Authenticated | Prompt 8E |
| Push | `GET /push/public-key`, `POST /push/subscribe`, `DELETE /push/subscribe` | Authenticated | Prompt 8E |
| Invoice | `GET /bookings/{key}/invoices` | Authenticated | Prompt 8F |
| Invoice | `PUT /bookings/{key}/invoices` | Authenticated | Body `InvoiceChange`; return snapshot, `skipped_duplicates`, `warnings`. No `expected_version`. Removal allowed only for the adding user or QC/Admin; Prompt 8F |
| Invoice | `GET /reports/invoices?period=YYMM`, `GET /export/invoices?period=YYMM&format=xlsx\|csv` | Admin, QC | Prompt 8F |
| Warmup | `GET /health/warm` | Public, rate limited | Prompt 8B |
| Realtime | `WS /ws?token=` | Authenticated | Event names in [ws-protocol.md](ws-protocol.md) |

### Note-save request

```typescript
{
  status_code: string
  note: string | null
  expected_version: number
  client_request_id: string // UUID; reuse on retries after uncertain outcomes
  confirm_new?: boolean
  allow_duplicate?: boolean
  assign_to?: number | null
  assign_message?: string | null
  invoices?: InvoiceChange | null
  supplier_name?: string | null
  supplier_type?: 'hotel' | 'transportation' | null
}
```

`supplier_name` and `supplier_type` are conditionally required for the first note of a new CW folder. `{key}` must be the canonical full key. A partial key returns `STATION_REQUIRED`, with `details.suggested_key` when known. Other malformed new keys return `INVALID_BOOKING_KEY`. Snapshot/version updates, note insertion, invoices, takeover notification, audit, and the persisted idempotency outcome are atomic.

Auth bodies/user responses are specified above by Prompt 3. Remaining envelopes not fully specified by Prompt 1B, including lookup aggregates and administrative request bodies, belong to their implementation prompts. Do not expose placeholder routes to fill those gaps.

## English UI copy

The complete copy catalogue, using the exact Prompt 1B keys, punctuation, capitalization, and interpolation variables, is in [`frontend/src/locales/en.json`](../frontend/src/locales/en.json). Existing foundation strings are preserved under their existing namespaces. `warmup` contains `Waking up the server…`; its subsequent state is separately stored as `warmup_ready: Ready`. The Markdown escape in `invoice_invalid` renders an underscore, not a literal backslash.

Supplier labels are `Hotel` and `Transportation`. Standard status labels are `Done`, `Rejection`, `Parking`, `Bundle`, and `HRS Preview`; labels in the locale do not hard-code or seed the database status catalogue. Period labels use `Aug 2026`. Display datetimes use `DD MMM YYYY HH:mm:ss` and an explicit timezone label, with the user's configured timezone (default `Asia/Ho_Chi_Minh`). All UI rendering remains plain text.

## Booking implementation details — Prompt 4

These envelopes clarify fields that Prompt 1B left implicit; existing shared DTO fields and error codes retain their names.

- `GET /bookings/lookup` returns `{booking_key,display_key,exists,version,resolution,format_warning,done_warning,snapshot,group,group_exists,suggestions,my_tasks,history}`. `history` is `{items:Note[],next_cursor}`. A missing/unresolved booking has `snapshot:null`, `version:0` and empty history/tasks; unresolved keys are null. `group` is null or `{cw_number,supplier_name,supplier_type,station_code}`. Partial input never writes. Missing full keys return `resolution.status:"exact"` but `exists:false`. Invalid input returns HTTP 200 with `resolution.status:"invalid"` and a warning; an existing malformed legacy key can be read but never written through note creation.
- `snapshot` in lookup/detail and list items use `BookingItem`: all `BookingSnapshot` fields plus flat `supplier_name`, `supplier_type`, `my_pending_tasks` (default 0), private `my_watching` (default false), and `stale_hours` (null unless stale). The task count is populated for list pages; lookup uses its private `my_tasks` array. Done warnings appear only when the last agent is another user. `GET /bookings/{key}` returns the same envelope, or 404 when absent.
- `POST /bookings/{key}/notes` returns HTTP 200 `{snapshot:BookingSnapshot,note:Note,my_watching:boolean}`, including on first creation and replay. A new booking requires `expected_version:0`. Existing version conflicts return the latest snapshot directly in `details`; if no booking exists yet, details is `{snapshot:null,version:0}`. Only canonical full paths can save; a normalized spelling is returned as `details.suggested_key` for noncanonical full input. Partial paths return `STATION_REQUIRED`, including a suggestion when the folder exists.
- `client_request_id` is a required UUID. The normalized request (including actor and canonical key) is fingerprinted. An identical retry returns the original committed response, even after newer notes, supplier edits, or a lost HTTP response. Reusing a UUID for another payload/user/key returns 422 `VALIDATION_ERROR`. This is not a mechanism for editing an existing note.
- Notes are at most 5,000 input characters. Control/format characters are removed; CRLF becomes LF and line breaks/tabs are retained. Whitespace-only notes fail when required. A new folder requires a cleaned 3–255-character supplier name and supplier type. Existing-folder supplier fields are ignored. Station mismatch includes `expected_station`, `suggested_key`, `display_key`.
- Inline `invoices` accepts the shared `InvoiceChange`, validates/uppercases/deduplicates numbers, enforces the 20-number limit and owner/QC/Admin removal, maintains invoice state/count and records the change in the note. DONE's `invoice_required` guard is active. Prompt 8F below implements cross-booking warnings and independent invoice APIs/reports.
- Prompt 8C implements near-key suggestions plus the `confirm_new` / `allow_duplicate` guards; see the explicit implementation contract below. Prompt 8D activates `assign_to` / `assign_message` with atomic assignment creation and recipient checks.
- Overall list adds `cw_number`, `station_code`, `supplier_type`, `period`, and `supplier` filters from Prompt 4. `q` matches a normalized booking-key prefix; supplier matches a normalized name prefix. `invoice` is an exact normalized invoice match. Dates must include a timezone and filter `updated_at` inclusively. Sort values are `updated_at_desc` (default) and `updated_at_asc`, with matching ID tie breakers. Pages are 1-based, sizes 1–100. Mine defaults to 10 and overall/stale to 20. Stale scope defaults to `mine`; Done is always excluded, thresholds are status-specific or 24 hours, and order is oldest activity first.
- `GET /notifications` returns `{items,unread_count}`; items include `id,type,booking_key,display_key,by_agent,note_id,task_id,created_at,read_at,merged_count`. Read/read-all return `{ok:true}`. Another owner's notification is 404.
- `GET /statuses` returns active `Status[]` ordered by `sort_order,id`. `PATCH /folders/{cw}` accepts supplier name/type and returns `group` fields directly; Admin/QC only. This single folder operation is implemented early to keep index/cache edits correct.
- `POST /notes/{id}/attachments` authenticates and checks note ownership (QC/Admin also allowed), then uses `NullStorage`. It intentionally returns **501 with code `INTERNAL`**, preserving the supplied error-code catalogue; a real provider/upload parser and download endpoint remain unimplemented. Another user's note is 404. Future upload limits: image/PDF, 5 MB each, 5 per note.
- Lookup/detail expose `Server-Timing: key_index;dur=..., snapshot;dur=..., notes;dur=...`; browser CORS permits it. Default/lookup/save/export route budgets are 8/6/12/55 seconds. A timeout returns 504, pool/row-lock exhaustion returns 503 with `Retry-After: 5`. Daily export uses the 55-second override in Prompt 8.

Operational limits, configuration and curl examples: [bookings.md](bookings.md).

## Folder search implementation details — Prompt 4B

Executable envelopes: `backend/app/schemas/folders.py`; generated frontend `SearchResponse` is a union discriminated by required `kind`. Existing shared `FolderCard`/`MonthRow` fields are retained, including mandatory display keys.

| `GET /search` kind | Fields in addition to `kind,query` |
| --- | --- |
| `booking` | `booking_key,display_key,exists,group` (group fields as lookup, or null); no history fetch |
| `partial_key` | `resolution:KeyResolution`, using the same resolver as lookup |
| `folder` | `folder:FolderCard,months:MonthRow[]` (all months) |
| `folders` | `items:FolderCard[],total,page,size` |
| `station` | `station:{code,name},sections:[{type:"hotel",items:FolderCard[]},{type:"transportation",items:FolderCard[]}],total,page,size` |
| `station_period` | `station:{code,name},period,period_label,items:BookingItem[],total,page,size` |
| `none` | `items:[]` |

`display_key` on the booking result follows the universal identity rule. `page,size` are explicit pagination additions to the shorthand Prompt 4B envelopes. Station sections split **one globally paginated, activity-ordered folder page**; `total` counts all matching folders, not only the page. Both section entries are always present. `BookingItem` is the Prompt 4 list DTO (the previously unspecified `BookingRow`); it includes Supplier and invoice snapshot fields, without private task queries.

Full-key misses return `booking` with `exists:false`. Partial `needs_station`/`ambiguous` remain `partial_key`. Missing exact folders, unknown station/period and unmatched Supplier/prefix searches return `none`. An out-of-range page with known matches retains its kind/total and an empty page. Exact CW means 5–10 digits; fewer digits mean prefix, with at most 20 folders per search page. Station/period keys are validated before Supplier text; malformed key-shaped input never triggers a Supplier LIKE scan.

`GET /folders/{cw}` returns `{folder,months}`. `GET /folders` returns `Page<FolderCard>` (size 1–100), sorted activity descending; filters are `station_code,supplier_type,q`. `PATCH /folders/{cw}` keeps its Prompt 4 body/response and Admin/QC ACL. `GET /stations?q=` returns `StationOption[]` directly: `{code,name:null|string,folder_count}`; response ETag/private max-age 60 and conditional 304 are supported. `PATCH /admin/stations/{code}` accepts required nullable `name` (max 100), returns `{code,name}`, Admin only, and returns 404 for unknown codes. All HTTP errors retain the existing code catalogue.

Search limit: `q` at most 100 characters, page size 1–20, default 120 requests/user/60 seconds. The whole DB fallback has a dedicated 3 s deadline. Supplier normalization, per-word prefix matching, relevance ordering, ETag invalidation, operational boundaries and reproducible benchmark commands: [folder-search.md](folder-search.md).

## Realtime implementation details — Prompt 5

`WS /api/v1/ws?token=` is implemented. Frames use `{event,data}` with the fixed business names; JSON application `ping`/`pong` are explicit transport additions needed for the ASGI/browser heartbeat. The complete field/close-code tables and reconnect rules are in [ws-protocol.md](ws-protocol.md). Executable models are `schemas/realtime.py`; generated `WebSocketClientFrame` / `WebSocketServerFrame` unions have required event discriminators.

Server booking/lock/notification payloads include `display_key` wherever `booking_key` occurs. Client lock commands send only canonical `booking_key`, consistent with the client identity rule. `notification.new` adds `type` for every notification (required for stale) and nullable `by_agent_name` for system reminders. Lock snapshot is `{locks:[{booking_key,display_key,user_id,user_name,expires_at}]}`; denial identifies the holder. Force logout data is `{reason,message}` without SID/token. `task.due` is implemented by Prompt 7B; its explicit payload is documented below and in ws-protocol.md.

Successful notes refresh KeyIndex/invalidate snapshots before manager-owned post-commit publication, which survives cancellation of the committed HTTP request. The saver’s own lease is released; another holder's advisory lease never prohibits note saving. UUID replays return the original response without duplicating booking events/notifications. Existing HTTP fields/errors are unchanged. Stale notifications/markers commit together without changing `updated_at`, version or last agent, and HTTP stale lists remain read-time truth. Default app wiring uses the real revocation manager; one backend process/instance is required.

## Frontend foundation — Prompt 6

No endpoint, JSON field or event name changes. The frontend uses the four existing
auth endpoints, private notification endpoints and Prompt 5 WebSocket frames.
`SESSION_REPLACED` displays the exact English UI copy. At the end of Prompt 6, Task/profile mutations and Home/Summary were reserved;
Prompts 7 and 7B implement those workflows below. Prompt 8 implements Admin/Reports data screens below.
Frontend configuration and refresh/request hooks are documented in [frontend.md](frontend.md).

## Prompt 7 read API clarifications

Existing `/bookings` filters `cw_number`, `station_code`, `period`, `supplier`, and
`supplier_type` support the Summary UI. Full-key `q` uses canonical equality; a partial
key uses CW + period equality. Other text `q` matches booking/station prefixes or a
substring of the normalized Supplier name. This intentionally expands the earlier
booking-prefix-only text behavior; it does not add smart folder search to Home.

`GET /users/lookup?q=&limit=20` is now implemented for Summary's Agent filter, brought
forward from the Prompt 8D directory contract. Authentication is required. It returns
an array of `{id,full_name}` for active users, sorted by full name/id. Optional q
matches full name or username with literal wildcard escaping; max q length is 100,
limit is 1–50. No username, password or session data is returned. Assignment endpoints
remain reserved. No existing endpoint, field name or event was renamed.

New-CW Supplier metadata and conditional invoice declaration use the existing
`NoteSaveRequest` fields; no invoice edit endpoint or assignment API was added.

## Task/profile implementation — Prompt 7B (including the Prompt 5B prerequisite)

Existing endpoint names and Task fields are retained. These clarify envelopes/body
details left open in Prompt 1B:

- `POST /bookings/{key}/tasks` accepts `{remind_date,remind_time?,message?,client_request_id?}`
  and returns HTTP 200 `Task`. Dates use `YYYY-MM-DD`, time is local `HH:mm` in
  `users.settings.timezone`; omitted time uses the profile default. The key is canonical.
- `GET /bookings/{key}/tasks` returns the owner's pending `Task[]` directly. `GET /tasks`
  accepts `view=pending|due|done`, one-based page and size (default 10, max 100), returning
  `{items,total,page,size}`. `GET /tasks/due` returns `{items,total}` with the first 100
  pending due tasks ordered by deadline/id and the exact total. Due means `remind_at <= now`;
  `is_overdue` is strictly before now.
- `PATCH /tasks/{id}` accepts optional `remind_date`, `remind_time`, `message`.
  `POST /tasks/{id}/snooze` accepts the same body and requires a date/time. Complete,
  snooze, edit and cancellation return the resulting `Task`; DELETE is a soft cancel.
  Other users' IDs return 404. Limits are five pending tasks per owner/booking.
- Create/reschedule must be future and within today +90 calendar days. Preserve an
  overdue deadline when only editing the message. Invalid local/DST times return
  `VALIDATION_ERROR`; exceeding the pending limit returns `TASK_LIMIT_REACHED`.
- UUID retry returns the original creation result, even after later changes, using
  migration `0003`. A different UUID payload/owner returns `VALIDATION_ERROR`.
  Complete/cancel tolerate repeating the same terminal action; snooze counts only
  a changed absolute deadline. No mutation is retried automatically by the UI.
- `PATCH /profile` accepts `{settings:{timezone?,default_remind_time?,task_sound?,web_notifications?,skip_weekends?}}`
  and returns the same public user as `/auth/me`. Settings merge with existing values;
  timezone is IANA, default time is `HH:mm`. No account/role fields can be changed here.
  Login/me now materialize defaults: business timezone, `09:00`, sound false, Web
  Notification false and skip weekends true. No OS permission is requested by the API.
- `task.due` data is explicitly `{task:Task,notification_id:number,created_at:UTC}`,
  sent privately after the task marker/notification commit. The outer frame remains
  `{event,data}`. Notification type is the existing `task_due`.

Detailed timing, retry, calendar and delivery semantics: [tasks.md](tasks.md).

## Smart folder UI clarification — Prompt 7C

`FolderCard` now includes the additive integer `stale_count` (default 0 for older
constructed DTOs). Every search/folder response populates it. It counts months with
`is_done=false` and activity at least the status-specific `stale_after_hours` or
`STALE_HOURS_DEFAULT` old, matching MonthRow.is_stale. The existing page-wide aggregate
computes it alongside booking/open counts; no N+1 queries or schema migration are added.
Existing paths, fields, enum values, key/display conventions and error codes retain
their names. Latest still means the largest period, not the most recently edited month.

The frontend uses the existing `/search`, `/folders`, `/folders/{cw}` and Admin/QC
`PATCH /folders/{cw}`. Full/partial keys always go directly to `/bookings/lookup`;
client classification selects the API and server `kind` controls presentation. The
classifier fixture is now shared at `fixtures/search-queries.json`.

Summary's `view=folders` and `from` query fields are client routing state, not new API
filters. Station/type/q/page map to the existing folder list parameters. A folder
booking event triggers targeted folder reconciliation, without a whole-page search
reload. See [smart-search.md](smart-search.md) for cache, navigation and manual checks.

## Admin, QC and Profile — Prompt 8

These endpoints are implemented. They use the existing `/api/v1` prefix/error codes;
additional response/request DTOs are generated from `schemas/admin.py`.

| Endpoint | Body/query | Response |
| --- | --- | --- |
| `GET /admin/users` | `q,page,size` | `Page<AdminUser>` |
| `POST /admin/users` | `username,full_name,role,temporary_password` | `AdminUser` |
| `PATCH /admin/users/{id}` | optional `full_name,role,is_active` (omit unchanged; no null) | `AdminUser` |
| `POST /admin/users/{id}/reset-password` | `temporary_password` | `AdminUser` |
| `POST /admin/users/{id}/kick` | none | `{kicked:boolean}` |
| `GET /admin/audit` | `page,size,user_id,action,entity,entity_id,date_from,date_to` | `Page<AuditEntry>` |
| `GET /admin/bookings/{key}/notes` | `page,size` | `Page<AdminNote>` including deleted notes; explicit history addition |
| `GET /admin/trash` | `q` (booking key), `page,size` | `Page<AdminNote>` for deleted notes |
| `DELETE /admin/notes/{id}` | `{reason}` | rebuilt `BookingItem` |
| `POST /admin/notes/{id}/restore` | none | rebuilt `BookingItem` |
| `GET /admin/statuses` | none | all `AdminStatus[]`, including inactive |
| `POST /admin/statuses` | full status creation fields | `AdminStatus` |
| `PATCH /admin/statuses` | `id` plus any changed status fields | `AdminStatus` |
| `GET /admin/stations` | `q,page,size` | `Page<StationOption>`; explicit admin pagination addition |
| `GET /reports/performance` | `period=day|week|month,date_from,date_to` (local dates) | `PerformanceReport` |
| `GET /export/daily` | `date,format=xlsx|csv,agent_id,status_code` | streamed download |
| `PATCH /profile` | optional `full_name,settings` | `PublicUser` |
| `GET /profile/stats` | none | `{notes_today,notes_this_week,timezone,login_history:AuditEntry[]}` |

Admin routes require Admin. Reports/export require Admin or QC. Profile requires the
active owner. `AdminUser` includes id, username, full_name, role, is_active, created_at,
last_login_at and has_session; it omits SID, password hash and personal settings.
Admin cannot disable/demote themselves (`FORBIDDEN`). Username duplicates use
`VALIDATION_ERROR`. Temporary passwords have 10–128 characters; names have 2–100.
Delete reasons have 3–255 characters. Audit filters use exact action/entity values;
time filters are aware UTC timestamps. Admin notes expose deletion actor/time/reason
and escaped note text, never save-request replay blobs. Default page size is 20/max 100.

`AdminStatus` adds `is_active,stale_after_hours` to the public status fields. Create
requires `code,label,position_label`; code is uppercase `[A-Z][A-Z0-9_]{0,39}`.
PATCH uses the base path with an `id` field, not an implicit `/statuses/{id}` route.
Nullable fields are `stale_after_hours,default_task_days`; other supplied fields cannot
be null. Disable with `is_active:false`; no hard-delete endpoint is exposed.

`PerformanceReport` contains period/date_from/date_to/timezone, note_count, done_count,
`users:[{agent,note_count,done_count}]`, `statuses:[{status,count}]`,
`trend:[{date,count}]`, `stale_by_user:[{agent,count}]`,
`stale_by_status:[{status,count}]`, `overdue_tasks_by_user:[{agent,count}]`.
Counts exclude deleted notes; Done is the current snapshot in the date range. Stale
and overdue are current totals. No task content is exposed. Cache TTL is 45 seconds.
Daily export columns/timezone/injection/cancellation rules are documented in
[admin-qc-profile.md](admin-qc-profile.md).

### Explicit event extension for moderation/catalogues

`booking.updated` adds `snapshot_rebuilt:boolean` (default false). Its
`last_agent_id,last_agent_name,status_code,position` may be null after all notes are
soft-deleted. The ID/name pair is null together. Clients must clear these fields rather
than retaining the previous agent/status. Rebuilt snapshots trigger review even when
the latest surviving author is the viewer. This is an explicit contract extension.

New `catalog.updated` data is `{resource:'users'|'statuses',snapshots_changed:boolean}`.
It is broadcast after committed catalogue/identity changes and contains no credentials
or private settings. Clients invalidate catalogue/snapshot data and refresh active views
without replacing unfinished drafts. See [ws-protocol.md](ws-protocol.md).

## Responsiveness — Prompt 8B

`GET /health/warm` is now public, rate limited to 10/minute/IP and runs SELECT 1.
It returns `{status:'ok',database:'connected'}` or the existing readiness 503 envelope;
exhaustion returns `RATE_LIMITED`/429 with Retry-After. `/health` remains DB-free.
`GET /statuses` requires authentication before conditional evaluation and returns
`Cache-Control: private, max-age=60`, `Vary: Authorization`, ETag and optional empty
304. Other personal responses default to no-store. `Server-Timing` preserves lookup
phase durations and adds `total` (to headers) and completed `db` cursor milliseconds.

Booking frames coalesce by canonical key over 100 ms, keeping the greatest version;
intermediate versions can be skipped. HTTP writes and histories still persist every
note. Outbox retries reuse the original `client_request_id` and immutable attempted
payload; a new business correction uses a new UUID/version after review.
[performance-8b.md](performance-8b.md) covers queue recovery and measured limits.


## Safeguards and integrity — Prompt 8C

Existing `Suggestion`, `NoteSaveRequest.confirm_new/allow_duplicate` and error-code
names are now active; no path or field was renamed. Missing full/resolved keys return
at most three suggestions. Unknown partial keys still return needs_station with no
suggestions. A missing write with suggestions requires confirm_new:true or returns
NEW_BOOKING_NEEDS_CONFIRM/422 with `details:{suggestions:Suggestion[]}`. Same-operation
UUID replay precedes all new guards. Duplicate matching live notes in the last 60 s
return DUPLICATE_RECENT_NOTE/409 with `details:{note:Note,seconds:number}`; only an
explicit allow_duplicate:true bypasses comparison. Both are nonretryable business
errors for the outbox; the frontend must not silently confirm new bookings.

| Admin endpoint | Query/body | Response |
| --- | --- | --- |
| GET /admin/integrity | page,size (default 20, max 100) | `{items:IntegrityRunDTO[],total,page,size,autofix_enabled,run_time,timezone}` |
| POST /admin/integrity/run | none | 202 IntegrityRunDTO; mode uses INTEGRITY_AUTOFIX (default false) |
| POST /admin/integrity/fix | `{run_id:number}` of a finished mismatched run | 202 new IntegrityRunDTO, full rescan/repair; does not edit the old report |

IntegrityRunDTO has `id,started_at,finished_at,checked,mismatched,fixed,status,details`.
Status is running/completed/failed/interrupted. Details contains mode report|fix,
trigger manual|scheduled, requested_by, source_run_id, scheduled_day, high_water_id,
items (max 200), truncated and sanitized error. Each finding has booking_key,
display_key, fields `{field:{actual,expected}}`, repairable and fixed. Samples are
bounded; counts and the repair pass cover the complete high-water scan. Missing
references use NOT_FOUND; invalid fix source uses VALIDATION_ERROR; concurrent start
uses SERVICE_BUSY/503 with Retry-After. Role is Admin for every integrity endpoint.

Snapshot authority is now the greatest non-deleted note ID, as specified in Prompt
8C. Admin moderation uses the same rule. Integrity also compares last_note_preview;
repair preserves invoices and operational updated_at, increments version and emits
the existing nullable booking.updated with snapshot_rebuilt:true. No new WebSocket
event or error code is invented. Run start/fix and individual repairs are audited.

Migration 0004 refines the already-present task-day column to SMALLINT NULL and adds
integrity_runs; prior migrations are unchanged. Rejection/Parking receive assumed
3/2-day defaults when null, preserving other configured values. See
[safeguards-integrity.md](safeguards-integrity.md) for scheduling, MAX-ID semantics,
cancellation, UI confirmations and measured scan/API latency.


## Collaboration — Prompt 8D

The reserved Watch/Assignment endpoints above are now implemented. Migration **0005**
adds watchers/assignments, merged_count and generated unique guards without modifying
old migrations. Full behavior, limits, ownership, defaults and wire extensions:
[collaboration.md](collaboration.md).

- PUT/DELETE `/bookings/{key}/watch` → `{watching:boolean}`; GET `/watching` →
  Page<BookingItem>. Default page/size 1/10; explicit additions above 200 return
  WATCH_LIMIT_REACHED. Missing/malformed bookings retain NOT_FOUND/INVALID_BOOKING_KEY.
- NoteSaveRequest accepts positive assign_to and optional assign_message<=255;
  self/inactive/missing/open-duplicate recipients return ASSIGNMENT_INVALID.
  Creation and recipient-note automatic completion are atomic with the note.
- GET `/assignments?view=to_me|from_me&status=open|done|declined&page&size=10`
  defaults to to_me/open. Returns Page<AssignmentItem>: id,note_id,booking_key,
  display_key,from_user,to_user,message,status,created_at,resolved_at,decline_reason.
  Each user object contains only id/full_name. POST `/assignments/{id}/complete`
  and `/decline {reason:string(1..255)}` return AssignmentItem, recipient only,
  404 for other callers. Repeated same outcome is idempotent; incompatible outcome
  after resolution is ASSIGNMENT_INVALID. Decline reason is persisted.
- GET `/users/lookup?q=&limit=20` remains id/full_name only, active users,
  q<=100, limit<=50, 120/minute/user, 10-second bounded cache with edit invalidation.
- `settings.auto_watch_on_note` defaults false and is PATCHable in Profile;
  automatic subscription is best effort at the 200 cap so the note can still save.
- BookingItem.my_watching and NoteSaveResponse.my_watching are explicit private
  additions; shared cached BookingSnapshot does not acquire user state.
  Original UUID replay retains its original watch flag along with the saved result.
- NotificationItem/notification.new add merged_count (default 1). Unread watch_update
  for a user/booking keeps its ID, replaces author/note/time and increments count
  up to 65,535. Reading frees the merge slot; next note creates a new ID. Previous
  agent/watch overlap receives taken_over only for that note. Assigned/completed
  workflow notices remain distinct. No type or existing path was renamed.
- Prompt 8E now activates the note-search command and its endpoint/view.


## Operations and PWA — Prompt 8E

Migration **0006** adds daily_reports and session-owned push_subscriptions without
editing prior migrations. Exact semantics/configuration/limits are documented in
[operations-pwa.md](operations-pwa.md); wire models are schemas/operations.py.

| Endpoint | Access | Result / body |
| --- | --- | --- |
| GET `/admin/system/health` | Admin | SystemHealth: 15-minute groups/total, approximate p50/p95/p99, DB/pool/sockets/locks/jobs, fingerprint-only slow queries, 120-point one-hour ring, uptime/version/degraded |
| GET `/reports/daily?date=` | QC/Admin | DailyReportDTO; omitted date uses today's business date; future date is VALIDATION_ERROR |
| GET `/reports/daily/export?date=` | QC/Admin | XLSX: Overview, Daily record, Stale; formula-safe, cancellable export deadline |
| GET `/search/notes?q&agent_id&status_code&date_from&date_to&page&size=20` | Authenticated | NoteSearchPage with grouped latest-match NoteSearchHit, match_count and date window/timezone/strategy metadata |
| GET `/push/public-key` | Authenticated | `{enabled:boolean,public_key:string|null}` |
| POST `/push/subscribe` | Authenticated | `{endpoint,keys:{p256dh,auth}}` → `{ok:true}` |
| DELETE `/push/subscribe` | Authenticated | `{endpoint}` → `{ok:true}`; non-owner endpoint is NOT_FOUND |

DailyReportDTO includes report_date, timezone, generated_at, cutoff_at, provisional,
note_count, new_booking_count, done_count, overdue_task_count, status_distribution,
agents, stations, stale, open_rejection_parking and repeated. All booking rows carry
canonical/display keys. Private frozen export source is stored internally and is
excluded from the JSON/schema. Past reports and their Excel source are immutable
after finalization; current-day reports cache for 60 seconds. Evening snapshots
finalize the next day to include late notes. Large JSON-column payloads use a
versioned compression envelope without changing the API result.

Note search q is trimmed 3–100 characters, 60 requests/minute/user. Dates are business
calendar dates YYYY-MM-DD, default inclusive 30 days, maximum 180; page defaults 1,
size defaults 20/max100. Deleted notes are excluded; total counts matching bookings.
LIKE is the default for TiDB. FULLTEXT requires the optional supported MySQL ngram
index and otherwise returns SERVICE_BUSY with a clear configuration message.

SystemHealth errors count 5xx and percentiles are histogram upper bounds. Metrics are
bounded process memory and reset on restart. SQL text/parameters are never retained.
An additive Admin-only WS event `system.health {degraded:boolean}` updates the menu
indicator after five sampled minutes of global p95 >500 ms and on connection.

Web Push supports task_due/assigned/watch_update only, offline active sessions only.
Subscribe requires validated browser-generated provider HTTPS endpoints/keys, and
records opt-in web_push_enabled in users.settings. A subscription cannot change
account ownership. It additionally binds current session_id, preventing delivery to
a replaced/logged-out device. Ten subscriptions/user; push mutation rate60/min/user.
404/410 cleanup and last_success_at are guarded against concurrent key/session edits.

New configuration: DAILY_REPORT_TIME (18:30), NOTE_SEARCH_STRATEGY (like), VAPID_PUBLIC_KEY,
VAPID_PRIVATE_KEY, VAPID_SUBJECT; INTEGRITY_AUTOFIX remains false. APP_VERSION and
SLOW_QUERY_THRESHOLD_MS are optional operational settings. Push is disabled without
valid matching VAPID configuration; it does not disable REST or the static PWA shell.

## Prompt 8F — Invoice declarations and reconciliation (implemented)

All paths below use `/api/v1`, the existing active-session guard and UTC timestamp
serializer. Invoice storage/behavior is described in [invoices.md](invoices.md).
Earlier declarations in this document that invoice warnings/independent APIs were
reserved describe the pre-8F stage; those features are now implemented.

| Method and path | Access | Response / behavior |
| --- | --- | --- |
| `GET /bookings/{key}/invoices` | Authenticated | `{invoice_state,items:Invoice[],number_pattern,max_per_booking}` |
| `PUT /bookings/{key}/invoices` | Authenticated | Body InvoiceChange; `{snapshot,invoices:Invoice[],skipped_duplicates:string[],warnings:[{invoice_number,booking_keys:string[]}]}` |
| `GET /reports/invoices?period=YYMM` | QC, Admin | InvoiceReport; omitted period uses the current BUSINESS_TIMEZONE period |
| `GET /export/invoices?period=YYMM&format=xlsx\|csv` | QC, Admin | Audited download; CSV=Invoices rows, XLSX=Invoices and Bookings sheets |

InvoiceChange supports optional add (up to 50 strings), remove_ids (up to 50 IDs),
no_invoice (boolean; false explicitly clears a declaration). Operations apply
remove → add → state under one booking lock/transaction. Missing IDs, IDs belonging
to another booking and already-present normalized numbers are safe no-ops. Removing
an existing row requires its adding user or fresh QC/Admin role; otherwise FORBIDDEN.
Inputs normalize before the configured pattern is checked; invalid numbers return
INVOICE_INVALID/details.invalid[], limits return INVOICE_LIMIT_REACHED and conflicting
no-invoice/remaining rows return INVOICE_STATE_CONFLICT. No partial write is committed.

**Decision: standalone PUT has no expected_version.** Its set semantics intentionally
allow concurrent additions to both succeed. Every successful PUT increments version,
including an uncertain no-op retry, but preserves last_*, Done and updated_at/stale
clock, creates no note/notification/takeover and only broadcasts booking.updated.
Inline invoices remain part of the note's expected_version/UUID transaction, with
INVOICE_REQUIRED when the selected status requires a declaration that is still
unknown after applying changes. An omitted invoices object preserves existing state;
an explicitly changed empty set is unknown unless no_invoice=true. Old Done/unknown
bookings remain readable/editable without a retroactive save requirement.

Lookup/detail add `invoices:Invoice[]` and
`invoice_rules:{number_pattern:string,max_per_booking:number}`. Note save adds
`invoices:Invoice[]|null`, skipped_duplicates and warnings; null is reserved for
persisted pre-8F UUID outcomes whose original response had no full invoice source.
A new note result includes real committed invoice IDs/authors/times. Note.invoice_change
continues `{added,removed,no_invoice:true|false|null}` and never owns invoice rows.
Lists retain state/count and at most three newest previews using one batch query.
MonthRow's existing state/count are populated. Soft delete/restore never edits invoices.

Search adds `{kind:"invoice",query,items:InvoiceSearchItem[],total,page,size}`.
InvoiceSearchItem extends BookingItem with matched_invoice. Explicit INV:/# use
exact normalized invoice matching. Empty Supplier TEXT results try that match once
only for a valid invoice number, returning none if still empty. Summary's invoice
parameter is exact; invoice_state accepts has_invoice/no_invoice/unknown. Existing
is_done and period filters compose with them.

InvoiceReport is `{period,period_label,bookings,with_invoice,no_invoice,not_declared,
invoice_total,multi_invoice_bookings,avg_per_booking,max_per_booking,
distribution:[{invoices:"0"|"1"|"2"|"3+",bookings}]}`. It aggregates bookings only
and caches 45 seconds; committed invoice changes invalidate it. Excel labels and
columns follow Prompt 8F exactly, respect EXPORT_BOOKING_KEY_STYLE and apply the
shared CSV/Excel injection guard. Export timeout/cancellation rules remain in force.
Daily record/new daily-report Excel append Invoice State, Invoice Numbers after
Note. DailyReportDTO adds done_not_declared:DailyBooking[]; DailyBooking adds invoice
state/count/previews. Frozen pre-8F reports keep their original totals/source rows;
missing new invoice cells export as Not declared/blank, with an empty missing new list.

Integrity scans now reconcile invoice count/state with actual rows; repair preserves
an empty explicit no_invoice, otherwise uses unknown/has_invoice from actual count.
The snapshot repair transaction/version/publication rules remain unchanged.

New environment controls: INVOICE_NUMBER_PATTERN (default
`^[A-Z0-9][A-Z0-9\-_/.]{2,39}$`), INVOICE_MAX_PER_BOOKING (20). Configured rules are
returned by lookup/invoice reads so frontend validation follows the backend.
No error-code spelling or endpoint name changed. These response extensions are
reflected in Pydantic and generated TypeScript schemas.


## Prompt 9 — Security contract additions

- `PublicUser` and `AdminUser` add `must_change_password:boolean`. Existing clients
  may treat an omitted public flag as false during deployment transition, but the
  server always enforces its own flag. New, seed and reset accounts require rotation.
- Only `GET /auth/me`, `POST /auth/logout` and `POST /auth/change-password` remain
  available to a restricted session. Other authenticated routes return
  `403 PASSWORD_CHANGE_REQUIRED`; WS rejects that session with 4401. Successful
  rotation clears the flag and revokes the token, requiring login again.
- New/reset passwords have 10–128 characters and cannot equal the username after
  NFKC/trim/casefold comparison. Login and old_password allow legacy lengths up to
  1024. Argon2id stores the original password without trimming or normalization.
- HTTP bodies are limited to 1,048,576 bytes before JSON parsing, including chunked
  requests and false Content-Length. Exceeding the limit returns 413
  `PAYLOAD_TOO_LARGE` in the standard error envelope. Notes remain capped at 5000
  characters; booking-key parsing rejects raw input over 100 **before** normalizing;
  lookup/search query validation is also capped at 100. Control characters are
  removed from note text (line breaks/tabs retained); invalid/control keys are
  rejected or normalized without ever storing the raw key.
- Login uses independent IP and username buckets (five failures / five minutes).
  Lookup and search share the bounded per-user search limiter. Retry-After is an
  ASCII integer number of seconds, including overload/timeout-related retry advice.
- HTTP responses include nosniff, frame DENY and strict-origin-when-cross-origin.
  Personal API responses have Cache-Control: no-store. Nonpersonal station/status
  catalogues retain their existing private ETag cache policy.
- WS requires an Origin equal to an exact CORS_ORIGINS entry (4403 otherwise), a
  valid nonrestricted session (4401 otherwise), text frames <=4096 UTF-8 bytes
  (1009 otherwise), and at most 20 messages in a rolling second (1008 otherwise).
  Limits are configurable. Missing Origin is rejected; diagnostic native clients
  must provide it. Slow-client sends retain their bounded timeout/eviction.
- Error envelopes never expose SQL text/parameters, stack traces or validation input.
  Completion/timeout logs use route templates rather than untrusted path content.
  Request IDs remain bounded; WebSocket token query strings are redacted.

These are explicit additive contract changes; existing paths/event names stay intact.
See [security-report.md](security-report.md) for review evidence and deploy setup.

## Prompt 10 additive diagnostics

Public `GET /health/db` and `GET /api/v1/health/db` share the DB probe and per-IP
10/minute limit. `/health` remains database-free. Errors retain the standard envelope.
Admin `GET /api/v1/admin/system/health` adds `operational_errors`
(`counts` keyed by `REQUEST_TIMEOUT` / `SERVICE_BUSY`, `window_seconds`, `threshold`), `key_index`
(`ready`, `keys`, `folders`, `container_bytes`) and `snapshot_cache`
(`entries`, `hits`, `misses`, `hit_ratio`). Container bytes describe shallow index
dictionaries; cache counters are process-lifetime. Existing fields are unchanged.
Daily report JSON may be served from a cached gzip representation according to
Accept-Encoding; decoded JSON fields and access rules remain unchanged.
Optional monitoring and retention environment variables are documented in
[observability.md](observability.md); backup settings in [backup.md](backup.md).
