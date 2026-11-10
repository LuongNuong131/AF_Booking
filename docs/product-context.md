# Product context

The user supplied Prompt 1 as the source of truth. Future prompts implement individual parts; do not expand the foundation into an unrequested business feature. All code, comments, UI, errors, and documentation are English. UI strings live in `locales/en.json` and must be ready for i18n.

## Purpose and architecture

- Internal status/note tracker for 20–100 staff and tens of thousands of bookings; actual booking processing is elsewhere.
- Admin-created accounts only; no registration. Agent, QC, and Admin roles, with authorization enforced by the backend.
- Vue 3/TypeScript/Vite/Pinia/Vue Router/Element Plus/VueUse/Axios/date-fns/vue-i18n on Vercel.
- Python 3.12/FastAPI/SQLAlchemy 2 async/aiomysql/Alembic/Pydantic 2 on Render.
- TiDB Cloud, MySQL-compatible protocol, configured through `DATABASE_URL` with verified TLS.
- WebSocket events are small and incremental; server-side pagination is mandatory. Route chunks load lazily. No N+1 queries.
- Pool size 5–10, pre-ping enabled, recycle at 280 seconds. One backend worker/instance until shared realtime coordination exists.

## Booking identity and lookup

- Canonical key: `CW{number}-{STATION}-{YYMM}`, for example `CW2154927-YUL-2608`. Normalize uppercase, remove whitespace, and map dash variants to ASCII `-`.
- Validation: `^CW\d{5,10}-[A-Z]{3}-\d{2}(0[1-9]|1[0-2])$`; station regex configurable with `STATION_CODE_PATTERN`.
- Display: `CW 2154927-YUL-2608`. Store only canonical keys; use them in URLs, WebSockets, caches, request hashing, and logs. Display formatting belongs at the presentation boundary and in exports/copy by default.
- Invalid legacy keys can still be looked up if present, but cannot create a new booking. Invalid new keys return `INVALID_BOOKING_KEY`.
- Missing-station partial keys, such as `CW2154654-2609`, must never be stored. Resolve an unambiguous folder/booking or return candidates; require a station for a new CW. Saving a note with a partial key returns `STATION_REQUIRED`, with a suggestion where possible.
- `booking_key` is ASCII with binary collation and a UNIQUE index. Add `(cw_number, period)` lookup indexing; JOIN key collations must match.
- Exact lookups use indexed equality. Never wrap indexed key columns in `LOWER`, `REPLACE`, or similar functions, and never use `LIKE` for the exact-key path.
- A RAM key index maps keys and CW/period/group metadata. Load in batches without delaying startup; use the DB until loaded. Update after committed writes and periodically reconcile counts/max IDs. It is an acceleration layer, never the source of truth.
- Smart search priority: full key, partial key, CW/prefix, station-period, station, supplier text. Folder results show CW and supplier and expand into monthly bookings.

## Notes, snapshots, and consistency

- Notes are append-only. Each save inserts a new note and updates `bookings.last_*`, `is_done`, `done_at`, and `version` in one transaction. Lists read booking snapshots rather than scanning note history.
- History loads lazily with cursor pagination. Do not fetch every note or booking.
- Statuses and their derived positions come from an Admin-managed table, not hard-coded enums.
- A Done warning names the last agent/time if another user marked it Done; it does not prevent another note.
- My bookings means `last_agent_id` equals the current user. A new note can move the booking between users' lists; notify the previous agent if different.
- `expected_version` provides optimistic locking; stale writes return 409 with the latest snapshot. No note may be lost.
- Each note request has a UUID `client_request_id`. Retrying after an uncertain timeout must reuse that UUID and return the original outcome if already committed.
- Only Admin can soft-delete/restore notes. Recompute snapshots from the newest undeleted note. Periodic integrity checks and an Admin repair tool must verify this invariant.
- Similar-key suggestions use small indexed IN lookups; creating despite suggestions requires confirmation. Duplicate normalized notes from the same user/status/key within 60 seconds require confirmation.

## Collaboration and user features

- Soft working locks are advisory, expire after 150 seconds idle, heartbeat every 30 seconds, and release on save/navigation/disconnection.
- One active session per user; new login invalidates the previous session.
- Agent: lookup, notes, personal and overall lists, profile, private reminders. QC additionally exports daily records and views reports. Admin additionally manages users, audit, statuses, trash, and note deletion.
- Audit login/logout/session eviction, user administration/password changes, note deletion/restoration, status changes, and exports.
- Staleness is calculated when reading using the current status's threshold or `STALE_HOURS_DEFAULT=24`. Background work only adds once-per-stale-episode notifications.
- Draft notes persist per canonical key for 7 days.
- Private tasks have pending/done/cancelled states and snooze, at most five pending tasks per user/booking, scheduled at most 90 days ahead. Due state is calculated on read; jobs supplement notifications. A booking status change does not cancel tasks.
- Users may watch bookings or assign work; an assignment completes when its assignee notes the booking.
- One CW number identifies a supplier and exactly one fixed station. Each month is a separate booking in that folder. First note for a new CW requires supplier name and Hotel/Transportation type. Agent, QC and Admin may classify a selected booking as Hotel/Transportation from its row or workspace. Each booking stores its own optional override; other months retain their own classification. Only Admin/QC may edit supplier names and recurrence settings. A station conflict returns `STATION_MISMATCH`.
- Invoices belong to bookings, not notes. `invoice_state` is `unknown`, `has_invoice`, or `no_invoice`. Enforce mutual exclusion and status-specific invoice requirements. Invoice normalization/regex/max count (default 20) are configurable; duplicates in other bookings warn. Separate invoice edits do not change note ownership or the staleness clock.

## Safety, time, and responsiveness

- Store UTC `DATETIME(3)`. User display timezone defaults to `Asia/Ho_Chi_Minh`, using `DD MMM YYYY HH:mm:ss` with a timezone label. Daily reporting follows `BUSINESS_TIMEZONE`.
- Render notes and booking inputs as plain text; never use `v-html`. Strip control characters. Prefix spreadsheet cells starting with `=`, `+`, `-`, `@`, tab, or newline to prevent formula injection.
- Optimistic UI updates reconcile in the background; retry network errors, roll back business errors. No full-page blocking overlays; release loading state in `finally`.
- Every API, database operation, WebSocket send, and job has a deadline. Default seconds: request 8, note save 12, export 55, DB connect/pool/lock wait 5, WS send 5, job 60. DB query/export budgets are 5000/30000 ms. Backend should time out before the frontend.
- Return `504 REQUEST_TIMEOUT` for request deadlines and `503 SERVICE_BUSY` with Retry-After for pool/lock contention. Cancelled transactions roll back; cancelled database connections must not re-enter the pool in a dirty state.
- Performance goals: ordinary API p50 <100 ms / p95 <300 ms, realtime <500 ms. With a local DB and 50,000 bookings, missing-key resolution <2 ms and lookup server p50 <10 ms / p95 <30 ms. Validate indexed point lookups in TiDB's native EXPLAIN output. These are future measured acceptance criteria, not claims about this release.
