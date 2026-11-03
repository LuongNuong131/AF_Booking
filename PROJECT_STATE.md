# Project state

## Implemented: Prompt 1 deployment foundation

- Vue 3 strict-TypeScript workspace with Pinia, lazy routing, Element Plus, VueUse, Axios timeouts, date-fns, and English vue-i18n messages.
- Responsive overview showing actual API/database connectivity, explicit unavailable/unconfigured states, and retry.
- FastAPI liveness/readiness endpoints, CORS allowlist, bounded requests with cancellation, Pydantic environment validation, and production docs restrictions.
- SQLAlchemy async/aiomysql engine with verified TLS, small bounded pool, pre-ping, 280-second recycle, UTC sessions, and finite database probe deadlines.
- Alembic connection runner, dependency locks with hashes, backend/frontend tests, and GitHub Actions.
- Vercel SPA deployment configuration, Render Blueprint, and TiDB Cloud deployment instructions.

## Not implemented

Full invoice management/reports, assignments/watch, service-worker Web Push, invoice exports, and integrity/recovery tools. Do not describe this as the completed booking application.

## Implemented: Prompt 1B shared contract

- `docs/api-contract.md` records all endpoint paths, request fields, access rules, pagination shapes, error codes, and explicit clarifications. `docs/ws-protocol.md` reserves the exact event names and directions; runtime frames/payloads remain for their implementation prompt.
- Pydantic wire models define booking snapshots, invoices, notes, statuses, tasks, suggestions, folders, months, key resolution, and pagination. Frontend TypeScript types are generated from these schemas; CI rejects stale generated files.
- HTTP errors use top-level `code`, `message`, and optional `details`, including validation, not-found, timeout, readiness, and internal errors. CORS and Retry-After headers are retained where applicable. Validation responses do not echo input secrets.
- English copy from Prompt 1B is stored with the supplied keys and interpolation variables. Status labels do not replace the Admin-managed status catalogue.
- `Task` and `FolderCard.latest` include `display_key` to satisfy the universal key/display rule.

## Implemented: Prompt 2 database schema

- Eleven SQLAlchemy mapped models, matching initial Alembic migration, InnoDB/utf8mb4 defaults, binary ASCII keys, unsigned IDs, and UTC DATETIME(3).
- Required indexes, with explicit ID tie breakers for TiDB ordered scans; no database foreign keys, duplicate booking-key index, or hash index.
- Canonical-key CHECK where enforcement is available, ORM storage validation fallback, and supplier-name normalization.
- Repeatable status and environment-supplied Argon2id admin seeding. Missing real admin credentials remain an operator configuration requirement.
- MySQL/TiDB disposable TLS tests verify migration parity, seeds/CLI, constraint behavior, eight index plans, the folder JOIN, rollback, and re-migration. Actual reports and assumptions are in docs/database-schema.md.
- Prompt 1B invoice/status/notification storage additions are retained without implementing their APIs.

## Implemented: Prompt 3 auth and authorization

- Four `/api/v1/auth` endpoints with Argon2 passwords, HS256 JWTs, configured token lifetime, generic failed-login errors, and no registration route.
- Single-device SID enforcement, active-user checks, bounded 12-second user/session cache, and immediate same-process invalidation on login/logout/password/kick/disable.
- Shared `get_current_user`, `require_roles`, database-session dependency, and authoritative rechecks for critical session mutations.
- Per-IP/account five-failure lockouts, safe request-ID logging/headers, DB-free `/health`, atomic auth audit records, and no-store auth responses.
- Internal `kick_session` / `set_user_active` helpers and an injectable `session.force_logout` transport interface, implemented by the Prompt 5 manager; no admin HTTP API yet.
- Unit tests plus disposable MySQL/TiDB auth integration suites, including cache/ACLs, concurrent login/password/logout scenarios, audit rollback, and transport failure.
- `JWT_SECRET_KEY` is an operator requirement; Render Blueprint can generate it. No default signing key/password is stored.

## Implemented: Prompt 4 booking backend

- Canonical/partial key parsing in Python and TypeScript using shared JSON fixtures.
- Exact/partial/ambiguous lookup, supplier reuse/station guards, active statuses and required note validation.
- Append-only note transaction with row locks, optimistic versions, atomic takeover notifications/audit and inline invoice changes.
- Durable UUID replay of the original response, migration `0002`, one retry for duplicate/deadlock races and authoritative session rechecks.
- Cursor history with batch attachment metadata, mine/overall/stale pages, batched private task counts and notification ownership.
- Startup keyset RAM index, periodic reconciliation, DB fallback, generation-guarded snapshot LRU and post-commit invalidation before realtime dispatch.
- Pure ASGI route deadlines, SELECT/lock/pool timeouts, cancellation rollback/connection discard, Server-Timing and safe WARNING logs.
- Admin/QC folder supplier edit and intentional NullStorage 501 attachment interface.
- Disposable TLS MySQL/TiDB booking tests added to CI; run instructions and explicit envelope clarifications in docs/bookings.md and docs/api-contract.md.

## Implemented: Prompt 4B folder/Supplier/station search

- Ordered query classification: full booking, partial key, exact CW, CW prefix, station/period, existing station, Supplier text. Key-shaped branches never run Supplier LIKE queries.
- Seven typed `/search` result variants, all-month folder detail, paginated/filtered folder list and immediate Admin/QC supplier edits.
- The existing KeyIndex GroupEntry now stores normalized Supplier words/activity; prefix-of-every-word matching ranks exact, starts-with, words, then recent activity. There is no separate Supplier index.
- Page-wide booking-count/open-count/latest-period aggregate uses the group/period index, with no per-folder queries. Station and station/period use existing indexes.
- Authenticated station autocomplete has a 60-second generation-guarded cache, ETag/304, private caching and Admin naming/audit. New folders and station renames invalidate station metadata.
- Search has a 100-character limit, per-user 120/minute sliding window and a dedicated three-second database fallback deadline.
- MySQL/TiDB tests cover classification, word/diacritic matching, rename visibility/ACL/audit, pagination, no-LIKE key branches, one-query aggregates and station caching. A reproducible 2,000-folder/50,000-booking benchmark verifies p95 and EXPLAIN plans; reports and limits are in docs/folder-search.md.
- Search wire types are generated as a discriminated union. No frontend screens or new database migrations were added.

## Implemented: Prompt 5 realtime and stale reminders

- Real `/api/v1/ws?token=` with REST JWT rules, fresh-row SID/active checks serialized with login, one socket per user, and actual 4401 rejection close codes.
- JSON `{event,data}` protocol with required display keys/UTC timestamps; typed frames/generated frontend unions; documented ping/pong and close/reconnect behavior.
- Bounded per-client FIFO writers, per-send deadlines, slow-client eviction, query-token log redaction and shutdown cleanup.
- Advisory one-user/one-booking leases, heartbeat/150-second TTL, 25-second sweep, snapshot/denial, safe same-SID replacement and save/disconnect/revocation release.
- Post-commit index/cache ordering, cancellation-independent booking broadcast and private takeover notification; UUID replays never duplicate publication.
- Auth login/logout/password/kick/disable now invoke the real SID-targeted force-logout manager; no no-op default transport remains.
- Independent asyncio scheduler jobs with startup catch-up, isolation/deadlines; durable once-per-stale-episode notifications preserve the booking activity clock and version.
- Real Uvicorn/WebSocket peers against disposable TLS MySQL/TiDB, plus unit tests for hung senders, bounded queues, scheduler failures and encoded-token redaction. No new migration; one instance/worker remains required.

## Implemented: Prompt 6 frontend foundation

- Real English sign-in and session restoration, bearer/error handling, immediate replaced-session logout and private-store cleanup; per-tab session storage.
- Role-guarded routes, canonical booking URLs, responsive dashboard shell, role navigation, user identity, theme controls and realtime indicator.
- Persistent light/dark/system themes, Element Plus on-demand components, visible keyboard focus and error boundaries.
- Private notification list/badge/read actions and canonical booking navigation; realtime frame validation, ping/pong, bounded reconnect and view refresh.
- Abortable generation-guarded requests with slow/timeout/retry UI, one GET-only retry, total deadlines, route watchdog and hidden-tab refresh.
- Scoped VueUse keyboard registration/help, shared key/date/avatar/status/empty components; tasks due-list/counter foundation.
- Strict TS with `@` alias; public VITE_API_URL/VITE_WS_URL and legacy API alias; build validation and frontend documentation.
- Vitest coverage and real Chromium/Vue/FastAPI/TLS TiDB flow, including roles, theme reload, notifications, backend restart and second-login logout; browser CI/screenshots.
- At the end of Prompt 6, Home/Summary/booking detail, Admin and Reports were layout shells; Prompt 7 below implements the booking pages. Profile displays account/theme only; reserved API mutations are not fabricated. No schema or backend application change.

## Implemented: Prompt 7 Home, Summary and booking detail

- Full/partial key lookup, instant resolved suggestions, ambiguity/station selection, shared summary/warnings/soft locks and cursor Activity.
- Dynamic status/note form, required notes/read-only Position, canonical UUID/versioned save, duplicate-click guard, latest-note conflict review and preservation of new typing.
- Per-user/key seven-day drafts with 500 ms debounce, restoration/discard, offline retention and real storage-failure feedback.
- Live 10-row My bookings/stale pages, takeover removal, first-page self promotion, later-page update counters and event-driven authoritative counts.
- 20-row server Summary with all requested filters, UTC conversion of zoned dates/Today, URL persistence, filtered return from detail and targeted realtime row hydration.
- Shared extensible BookingTimeline, NoteForm, BookingSummaryCard, LockBadge, DoneWarning and BookingTable, with slots for later Task features.
- Short bounded read cache, private session cleanup, generation/version guards, replay of events racing page reads and disposed-view debounce guards; no polling.
- Existing listing filters reused. Text q now searches normalized Supplier names/stations as well as booking prefixes; exact/partial keys use equality. The public active-user summary directory is implemented early for the Agent filter.
- Minimal Supplier creation fields and conditional invoice declaration support existing backend save requirements; Prompt 7C below adds smart folder search. Full invoice management remains later scope.
- Frontend units and real Chromium/TLS TiDB two-user collaboration flow; backend listing/directory regressions on MySQL/TiDB. No migration or runtime dependency change.

## Implemented: Prompt 7B reminder tasks

- TaskDialog, TaskList, TaskReminderToast and DueTasksModal integrated with Home, booking cards/lists and Alt+T. Quick date chips, nonblocking ten-second save suggestions and English zoned confirmations.
- Private task APIs and profile settings, brought forward from the missing Prompt 5B prerequisite. Five pending reminders per user/booking, UUID creation replay, atomic limits/audit, local date/time validation and migration 0003.
- Startup/30-second due scheduler with durable once-per-deadline notifications and private typed task.due frames; HTTP catch-up after login/reopen/reconnect without polling.
- Optimistic actions/rollback, late-event guards, booking warnings patched in place, pending-task bells, due count/title and completion-to-note navigation.
- Profile defaults/timezone/skip-weekends/sound/Web Notification settings persisted with explicit permission controls; sound only after interaction. Native browser notifications are implemented; service-worker push remains future scope.
- Vitest calendar/DST/dialog/event/rollback/permission/audio checks, private API/concurrency/TLS database tests and a third real Chromium flow. Read docs/tasks.md for retry semantics, deployment and manual checks.

## Implemented: Prompt 7C smart search and folder views

- One Home smart input routes full/partial keys directly to lookup, debounces other searches at 200 ms, cancels old reads and renders the server discriminator. Python/TypeScript share a classification fixture.
- Supplier folder cards, station/type sections, station-period rows, month browsing/New month, breadcrumbs, arrow/Enter selection and Escape/empty-Backspace navigation preserving note drafts.
- New-CW station/Supplier guards, trimmed three-character name minimum, type shortcuts, read-only identity, station-mismatch application and Admin/QC supplier edits.
- Summary Bookings/Folders mode, 20-folder server pages, station autocomplete/type/name-CW filters in URLs and folder/detail/return routes.
- Shared 50-entry SWR LRU, 30-second freshness, per-session cancellation and data guards; immediate month patches plus coalesced targeted folder hydration with four-read concurrency. Recent folders are per user, max ten; command palette remains Prompt 8D.
- Explicit additive FolderCard.stale_count, calculated in the same page-wide aggregate with status thresholds and no N+1. No migration; head remains 0003. First 20 months with virtual scrolling above 50.
- Vitest classification/card/breadcrumb/keyboard/validation/cache/cancellation coverage, two-engine folder regressions/performance and a fourth Chromium flow. Read docs/smart-search.md and docs/testing.md.

## Next implementation steps

1. Confirm the provisional Position labels when the business mapping is available.
2. Add Admin APIs using the provided role checks and session-invalidation helpers when requested.
3. Continue Prompt 8 and later prompts for the remaining workflows.

## Deployment status

Configuration is committed for Vercel frontend, Render backend, and TiDB Cloud database. Hosted resources and credentials must be configured in those providers. A successful local test or Git push does not establish a live production deployment.

## Implemented: Prompt 8 Admin/QC/Profile

- Admin users, audit filters, booking moderation/history, trash/restore, dynamic statuses and paginated Supplier/Station management; fresh transaction authorization and self-lock/demotion prevention.
- Snapshot rebuild/version/event on soft delete/restore, no loss of invoices. Nullable cleared-snapshot events and explicit `catalog.updated` are documented in API/WS contracts.
- SQL performance aggregates, private-task counts, 45-second report cache, lazy Chart.js, streaming safe daily CSV and write-only XLSX with business-timezone boundaries and disconnect cleanup.
- Profile display name, password/session revocation, timezone/reminder preferences, personal counts and login history.
- Schema head remains 0003; dependencies/locks include openpyxl and Chart.js.

## Implemented: Prompt 8B responsiveness

- Durable per-user 50-note outbox, immediate timeline/snapshot/My bookings preview, backoff with immutable UUID replay, business-error rollback/conflict review and offline/reload recovery.
- Warmup endpoint/UI and IP rate limit, parallel bootstrap, 150 ms key prefetch/Enter sharing, 30-second LRU/SWR, status ETag/304 and local catalogue persistence.
- Route/detail hover/idle preloads, virtualized long timeline/table, shallow list state, v-memo, animation-frame updates, 100 ms server coalescing, GZip/ORJSON and HTTP/DB timing diagnostics.
- Local font/preconnect/immutable assets, direct Render requests, Singapore Blueprint region. Raw MySQL/TiDB before/after lookup reports and limitations are in docs/performance-8b.md.
- Test evidence is recorded in docs/testing.md. Hosted deployment credentials remain operator-provided; no provider resources have been provisioned.
