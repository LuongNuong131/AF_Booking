# API contract — Prompt 1B

This document records the user's shared contract for all implementation prompts. Paths, JSON field names, and error codes must not change silently. Update this file and the wire models together if an approved change is needed.

**Implementation status:** the foundation exposes only the infrastructure probes described below. This step adds shared schemas, generated frontend types, standard error responses, and the English copy catalogue. The business endpoints in this document are contracts for later prompts, not implemented handlers.

## Common conventions

- HTTP and WebSocket paths use the `/api/v1` prefix. The endpoint table omits this common prefix.
- JSON keys use `snake_case`. Output timestamps are UTC ISO 8601 strings with milliseconds, such as `2026-11-02T08:15:30.123Z`. Naive timestamps are rejected by the shared models; aware timestamps are normalized to UTC on serialization.
- Page pagination: `{items, total, page, size}`. Pages are one-based. Cursor pagination: `{items, next_cursor}`; `next_cursor` is explicitly `null` at the end. Cursors are opaque to the frontend.
- Errors always use `{code, message, details?}` at the top level. Do not wrap them in `error` or FastAPI's default `detail`. Messages are English; clients branch on `code`, not message text.
- Any object containing `booking_key` also contains `display_key`, including nested objects. Requests, comparisons, URLs, caches, and WebSocket identities use the canonical key; UI uses the display key. A key such as `CW2154654-RDU-2609` displays as `CW 2154654-RDU-2609`.
- In FastAPI, declare `/bookings/mine`, `/bookings/stale`, and `/bookings/lookup` before `/bookings/{key}`. Apply the same fixed-path-before-parameter rule to other groups.
- Authenticated means a valid active session. Admin/QC checks and ownership checks belong on the backend. Other users' tasks return 404, not 403. Notifications are private to their owner.

## Wire types

The complete executable field definitions are in [`backend/app/schemas/contracts.py`](../backend/app/schemas/contracts.py). Frontend equivalents are generated in [`frontend/src/types/api.generated.ts`](../frontend/src/types/api.generated.ts); do not edit that file manually.

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
- WebSocket event names are reserved below, but Prompt 1B does not define an envelope or detailed payload schemas. These must be documented before the corresponding runtime implementation; no payload shape is invented in this step.

## Endpoint catalogue

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

`supplier_name` and `supplier_type` are conditionally required for the first note of a new CW folder. `{key}` must be the canonical full key. A partial key returns `STATION_REQUIRED`, with `details.suggested_key` when known. Other malformed new keys return `INVALID_BOOKING_KEY`. Snapshot/version updates, note insertion, and the idempotency outcome must be atomic when implemented.

The exact response envelopes not fully specified by Prompt 1B (such as auth user fields, lookup aggregate fields, and administrative request bodies) remain for their implementation prompts. Do not expose placeholder routes or invent response names to fill those gaps.

## English UI copy

The complete copy catalogue, using the exact Prompt 1B keys, punctuation, capitalization, and interpolation variables, is in [`frontend/src/locales/en.json`](../frontend/src/locales/en.json). Existing foundation strings are preserved under their existing namespaces. `warmup` contains `Waking up the server…`; its subsequent state is separately stored as `warmup_ready: Ready`. The Markdown escape in `invoice_invalid` renders an underscore, not a literal backslash.

Supplier labels are `Hotel` and `Transportation`. Standard status labels are `Done`, `Rejection`, `Parking`, `Bundle`, and `HRS Preview`; labels in the locale do not hard-code or seed the database status catalogue. Period labels use `Aug 2026`. Display datetimes use `DD MMM YYYY HH:mm:ss` and an explicit timezone label, with the user's configured timezone (default `Asia/Ho_Chi_Minh`). All UI rendering remains plain text.
