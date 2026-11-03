# API contract — Prompt 1B

This document records the user's shared contract for all implementation prompts. Paths, JSON field names, and error codes must not change silently. Update this file and the wire models together if an approved change is needed.

**Implementation status:** probes/auth and Prompt 4 booking lookup, notes, lists, status catalogue, notifications, and Admin/QC supplier-folder edits are implemented. Attachments intentionally return 501 through NullStorage. Prompt 4B additionally implements search, folder lists/detail, station autocomplete and Admin station naming. Prompt 5 implements WebSocket updates/soft locks/private notifications/session logout and stale reminder jobs. Task mutations and later-prompt endpoints remain reserved.

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
| `FolderCard` | `cw_number`, `supplier_name`, `supplier_type`, `station_code`, `booking_count`, `open_count`, `last_activity_at`, `latest:{booking_key,display_key,period_label,status,agent}\|null` |
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

### Auth implementation details — Prompt 3

- `POST /auth/login` accepts JSON `{username,password}`. Success returns `{access_token,user,token_type:"bearer",expires_in}`; the last two fields are explicit additions for bearer-token clients. `expires_in` is seconds (default 43200).
- `user` and the direct `GET /auth/me` result contain `id`, `username`, `full_name`, `role`, `is_active`, and `settings` (JSON or null). They never include `password_hash` or `current_session_id`.
- `POST /auth/logout` returns `{message:"Signed out."}` and revokes the current SID.
- `POST /auth/change-password` accepts `{old_password,new_password}`. Success returns `{message:"Password changed. Please sign in again."}` and revokes the session. The client must sign in again. A wrong old password or invalid new password is `422 VALIDATION_ERROR`. New passwords have 12–1024 characters.
- Authenticated requests use `Authorization: Bearer ...`. JWTs require valid HS256 signatures, issuer/audience, expiration, user ID, role, and UUID SID. Invalid/expired tokens and inactive/deleted users return `401 UNAUTHORIZED`; an active user's replaced/cleared SID returns `401 SESSION_REPLACED`. Permissions use the current user role, not a stale JWT role alone.
- The first five invalid credential attempts return 401; later attempts in the lockout return `429 RATE_LIMITED` with `Retry-After`. Cache/session invalidation and in-memory scope are documented in [auth.md](auth.md).
- Every HTTP response has `X-Request-ID`; browser CORS exposes it and `Retry-After`. Auth responses use `Cache-Control: no-store`.

No registration, refresh-token, booking, or admin-management endpoint is added in Prompt 3. Prompt 5 now implements that internal callback through the real WebSocket manager and defines its wire frame in ws-protocol.md.

| Code | HTTP | Details / behavior |
| --- | --- | --- |
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
- Prompt 1B reserved the event names below. Prompt 5 now defines `{event,data}` and exact implemented payloads in [ws-protocol.md](ws-protocol.md); `task.due` remains for Prompt 5B.

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
- `snapshot` in lookup/detail and list items use `BookingItem`: all `BookingSnapshot` fields plus flat `supplier_name`, `supplier_type`, `my_pending_tasks` (default 0), and `stale_hours` (null unless stale). The task count is populated for list pages; lookup uses its private `my_tasks` array. Done warnings appear only when the last agent is another user. `GET /bookings/{key}` returns the same envelope, or 404 when absent.
- `POST /bookings/{key}/notes` returns HTTP 200 `{snapshot:BookingSnapshot,note:Note}`, including on first creation and replay. A new booking requires `expected_version:0`. Existing version conflicts return the latest snapshot directly in `details`; if no booking exists yet, details is `{snapshot:null,version:0}`. Only canonical full paths can save; a normalized spelling is returned as `details.suggested_key` for noncanonical full input. Partial paths return `STATION_REQUIRED`, including a suggestion when the folder exists.
- `client_request_id` is a required UUID. The normalized request (including actor and canonical key) is fingerprinted. An identical retry returns the original committed response, even after newer notes, supplier edits, or a lost HTTP response. Reusing a UUID for another payload/user/key returns 422 `VALIDATION_ERROR`. This is not a mechanism for editing an existing note.
- Notes are at most 5,000 input characters. Control/format characters are removed; CRLF becomes LF and line breaks/tabs are retained. Whitespace-only notes fail when required. A new folder requires a cleaned 3–255-character supplier name and supplier type. Existing-folder supplier fields are ignored. Station mismatch includes `expected_station`, `suggested_key`, `display_key`.
- Inline `invoices` accepts the shared `InvoiceChange`, validates/uppercases/deduplicates numbers, enforces the 20-number limit and owner/QC/Admin removal, maintains invoice state/count and records the change in the note. DONE's `invoice_required` guard is active. Cross-booking duplicate warnings and independent invoice APIs/reports remain for Prompt 8F.
- Suggestions and the `confirm_new` / `allow_duplicate` guards belong to Prompt 8C: `suggestions` is currently empty and these flags reserve their contract fields. `assign_to` / `assign_message` return `ASSIGNMENT_INVALID` until Prompt 8D; requests are never silently treated as assigned.
- Overall list adds `cw_number`, `station_code`, `supplier_type`, `period`, and `supplier` filters from Prompt 4. `q` matches a normalized booking-key prefix; supplier matches a normalized name prefix. `invoice` is an exact normalized invoice match. Dates must include a timezone and filter `updated_at` inclusively. Sort values are `updated_at_desc` (default) and `updated_at_asc`, with matching ID tie breakers. Pages are 1-based, sizes 1–100. Mine defaults to 10 and overall/stale to 20. Stale scope defaults to `mine`; Done is always excluded, thresholds are status-specific or 24 hours, and order is oldest activity first.
- `GET /notifications` returns `{items,unread_count}`; items include `id,type,booking_key,display_key,by_agent,note_id,task_id,created_at,read_at`. Read/read-all return `{ok:true}`. Another owner's notification is 404.
- `GET /statuses` returns active `Status[]` ordered by `sort_order,id`. `PATCH /folders/{cw}` accepts supplier name/type and returns `group` fields directly; Admin/QC only. This single folder operation is implemented early to keep index/cache edits correct.
- `POST /notes/{id}/attachments` authenticates and checks note ownership (QC/Admin also allowed), then uses `NullStorage`. It intentionally returns **501 with code `INTERNAL`**, preserving the supplied error-code catalogue; a real provider/upload parser and download endpoint remain unimplemented. Another user's note is 404. Future upload limits: image/PDF, 5 MB each, 5 per note.
- Lookup/detail expose `Server-Timing: key_index;dur=..., snapshot;dur=..., notes;dur=...`; browser CORS permits it. Default/lookup/save/export route budgets are 8/6/12/55 seconds. A timeout returns 504, pool/row-lock exhaustion returns 503 with `Retry-After: 5`. Export routes are reserved, but the decorator supports their future override.

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

Server booking/lock/notification payloads include `display_key` wherever `booking_key` occurs. Client lock commands send only canonical `booking_key`, consistent with the client identity rule. `notification.new` adds `type` for every notification (required for stale) and nullable `by_agent_name` for system reminders. Lock snapshot is `{locks:[{booking_key,display_key,user_id,user_name,expires_at}]}`; denial identifies the holder. Force logout data is `{reason,message}` without SID/token. `task.due` stays reserved and is not assigned an invented payload here.

Successful notes refresh KeyIndex/invalidate snapshots before manager-owned post-commit publication, which survives cancellation of the committed HTTP request. The saver’s own lease is released; another holder's advisory lease never prohibits note saving. UUID replays return the original response without duplicating booking events/notifications. Existing HTTP fields/errors are unchanged. Stale notifications/markers commit together without changing `updated_at`, version or last agent, and HTTP stale lists remain read-time truth. Default app wiring uses the real revocation manager; one backend process/instance is required.
