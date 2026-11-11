# Project state

## Implemented: Booking ticket history and note-search UX

- Booking information includes paginated pending/handled ticket lists with counts, creator, attachment count, QC result and links to the correct ticket. Agent visibility remains limited to their own tickets; QC/Admin retain booking-wide access.
- The create action opens/focuses the composer; successful creation refreshes both status lists. Notification and workspace refreshes also update history.
- Summary note search has responsive themed filters/results, business-date presets, safe highlighted excerpts, expand/collapse, explicit applied-filter context, URL persistence and page correction. Draft edits do not silently change pagination queries.
- Existing API/role rules and database schema are unchanged. See `docs/booking-ticket-history-note-search-vi.md`.

## Implemented: Prompt 1 deployment foundation

- Vue 3 strict-TypeScript workspace with Pinia, lazy routing, Element Plus, VueUse, Axios timeouts, date-fns, and English vue-i18n messages.
- Responsive overview showing actual API/database connectivity, explicit unavailable/unconfigured states, and retry.
- FastAPI liveness/readiness endpoints, CORS allowlist, bounded requests with cancellation, Pydantic environment validation, and production docs restrictions.
- SQLAlchemy async/aiomysql engine with verified TLS, small bounded pool, pre-ping, 280-second recycle, UTC sessions, and finite database probe deadlines.
- Alembic connection runner, dependency locks with hashes, backend/frontend tests, and GitHub Actions.
- Vercel SPA deployment configuration, Render Blueprint, and TiDB Cloud deployment instructions.

## Not implemented

Broader recovery tools and later-prompt features. Do not describe this as the completed booking application.

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

## Remaining operator configuration

Confirm the provisional business Position labels. Provision Vercel, Render and TiDB
Cloud, then configure real origins, TLS database credentials and signing secrets.
Optional Sentry, VAPID and scheduled backup credentials remain operator settings.

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

## Implemented: Prompt 8C safeguards and snapshot integrity

- Bounded numeric CW edits/month suggestions through KeyIndex or a single indexed fallback; explicit new-booking confirmation in UI/server.
- Normalized same-user/status/booking duplicate detection over 60 seconds, preserving UUID replay; explicit Send anyway/Cancel and outbox business-error recovery.
- Status-specific reminder date/selected chip; new migration 0004 narrows the early task-day field and seeds assumed 3/2 defaults without editing prior migrations.
- Durable integrity_runs, high-water/keyset 1000-row MAX-live-note-ID scans, 50 ms yields, 200 findings limit, nightly business-time scheduling/catch-up, report-only default and opt-in autofix.
- Admin history/progress/details/confirmed repair, per-booking locks/fresh ACL/audit/cache/index/realtime and preserved operational clock/invoices. Interrupted runs recover explicitly.
- docs/safeguards-integrity.md records API/migration/manual checks and 50k-booking/50k-note measurements on both engines; raw reports include EXPLAIN and concurrent lookup latency.


## Implemented: Prompt 8D collaboration

- Migration 0005 adds watchers/assignments and unread merge/open-assignment generated unique guards; old migrations remain unchanged.
- Personal watch endpoints/200 cap, opt-in automatic following, private watch flags, single-query watcher fanout and one multi-row notification insert/upsert.
- Same-ID unread watch merging, counter/badge reconciliation and takeover deduplication; no offline notification loss.
- Atomic note assignments with fresh sorted recipient locks, active/self/open guards, automatic note completion, recipient-only complete/decline with reason and idempotent retry.
- Minimal cached/rate-limited active-user directory; assignment/watch Home tabs, incoming/outgoing filters, profile preference and persisted assignment drafts/outbox.
- Lazy role-aware Ctrl+K palette, canonical/partial booking opening, ten per-user recent bookings, recent folders, theme/task/watch/export/sign-out commands.
- Central scoped useShortcuts, typing/IME guards, roving J/K/arrows/Enter/W/T/paging and extended ? help; note search is explicitly disabled until Prompt 8E.
- MySQL/TiDB migration/API/private-WebSocket tests, frontend units and a three-user Chromium flow; details in docs/collaboration.md.


## Implemented: Prompt 8E operations and analysis

- New migration0006 adds daily_reports and session-owned push_subscriptions; prior migrations remain unchanged. pywebpush is hash-locked; frontend PWA uses existing Vite/Node.
- Bounded O(1) request counters, 15-minute approximate histograms, DB/pool/WS/lock/job state, fingerprint-only slow queries and a 120-point ring; Admin health view refreshes only while visible, with Admin-only WS degradation indicator.
- Consistent RR daily aggregates, station/type tables, immutable past JSON and frozen Excel source, 60-second provisional cache/evening job/next-day finalization and compressed large payloads without truncation.
- Typed date-bounded/rate-limited note search, default indexed LIKE for TiDB, optional verified MySQL ngram strategy, safe Unicode text-node/mark highlighting and enabled Summary/palette entry.
- Production manifest/icons/static-only worker, offline shell, no API caching, explicit update banner and draft-safe reload across tabs.
- VAPID-backed bounded push queue for offline current sessions only; explicit Profile opt-in, endpoint ownership/provider/key validation, TLS/no-redirect transport, dead/stale cleanup and minimal booking-only content.
- Real MySQL/TiDB operations/optional-FT/schema tests, VAPID encryption with intercepted transport, frontend units and production PWA/operations Chromium flows. Real provider/device delivery needs operator VAPID configuration; physical iOS has not been validated.


## Implemented: Prompt 8F invoice management

- Additive migration 0007 for normalized invoice uniqueness/lookups, reconciliation indexes and unsigned SMALLINT count; old migrations and explicit declarations preserved.
- One locked invoice service for note/standalone edits, full author/time data, duplicates/warnings, owner/QC/Admin removals, grouped audit, stable operational clock and invoice-only realtime.
- Exact INV:/# search, Supplier fallback, Summary filters, single-batch previews, integrity detection/repair and independent note moderation.
- Monthly one-query reconciliation/cache, safe streamed two-sheet invoice Excel/CSV, daily invoice columns and unknown Done lists with immutable report compatibility.
- Reusable InvoicePanel/chips/copy/shortcuts, badges, Reports panel, timeline changes and the shared durable note/invoice outbox with draft retention.
- Shared parsing fixtures, transaction/permission/concurrency/export/query-budget regressions and the invoice Chromium flow. See docs/invoices.md and docs/testing.md.


## Implemented: Prompt 9 security hardening

- Migration 0008 and restricted initial-password sessions; seed/new/reset require rotation, reusable authorization and immediate cache/SID revocation retained.
- Independent IP/account login protection, strict HS256 required claims, production signing-key validation, bounded text/path/body input and parameterized database session configuration.
- Exact HTTP/WS origins, inbound WS byte/rate limits, existing slow-client eviction, response headers/no-store, sanitized route/error logging.
- Shared localStorage tokens, explicit expiry/cross-tab cleanup, one physical WebSocket per same-browser session via Web Locks/BroadcastChannel, dedicated first-password screen.
- Build-generated Vercel Build Output API routes and exact CSP origins from the bundle environment; missing/insecure production endpoints fail the build. External theme script, no unsafe script inline/eval, style-only inline exception documented.
- Whole-frontend vue/no-v-html lint and negative probe, exact dependency pins/hash locks, pip-audit/npm audit gates, automated security regression tests and report in docs/security-report.md.
- Hosting is still prepared configuration only. Actual Render URL/CORS/CSP and TiDB credentials are entered when provisioning providers; no live deployment is claimed.

## Implemented: Prompt 10 testing, CI, observability and recovery

- Hash-locked pytest-cov/Locust/Sentry dependencies; real verified-TLS MySQL/TiDB
  service coverage, shared factories and fresh schema migrations. CI gates service
  coverage at 80%, alongside security audits, FE lint/types/tests/build and browser jobs.
- Browser deadline/slow/retry, delayed-acknowledgment UUID replay, all note shortcuts,
  retained Done/Parking history and held simultaneous-save conflict cases.
- Reproducible synthetic 50k booking/250k note/2k folder/40 station load harness,
  50 concurrent actors, 100 WS peers, four key groups and real delayed-DB recovery.
  Raw measured evidence is documented. Current mixed REST/key p95 targets remain
  unmet on this shared runner; the strict manual load gate reports failure.
- JSON request identity/timing, fingerprint-only slow SQL, bounded 503/504 alert
  counters, index/cache metrics, throttled public DB probe and optional scrubbed Sentry.
- Independent bounded retention with additive migration 0009; report/search/lookup
  query and event-loop optimizations preserve the API contract and private data rules.
- Typed all-table consistent backups, AES-GCM/checksums, safe empty-target recovery,
  actual CLI round-trip tests and opt-in scheduled encrypted GitHub artifacts.
- Provider deployment, external monitoring delivery and production backup scheduling
  have not been activated. See docs/testing.md for the current verification record.

## Audit: 05 Nov 2026

- Current Alembic head is **0010**. Deployment/security documentation now points to
  0010; older per-prompt migration numbers in historical sections are not release
  prerequisites by themselves.
- Backend local gates pass with an isolated test environment: Ruff check, format check,
  generated contract check, and **180 unit tests passed**. **162 database/browser tests
  are skipped** unless the disposable MySQL/TiDB runner is configured; skips are not
  counted as integration passes.
- Frontend lint, strict typecheck, security probe, npm audit and **245 Vitest tests
  pass**. Production build requires an explicit `VITE_API_URL`; CI supplies the public
  fixture URL and local validation must do the same.
- Fixed CI/test environment leakage from `SENTRY_DSN`, and corrected scope/deployment
  documentation. Remaining known limitations are real attachment storage (currently
  `NullStorage`/501), Redis coordination for multi-instance deployment, external
  Telegram/email notifications, and unmet mixed-load p95 targets on the shared runner.

## Implemented: Prompt 12.1 note snippets

- Additive migration **0010** adds user-private snippets with per-user title
  uniqueness, usage ranking and updated timestamps.
- CRUD/search/use endpoints are owner-scoped, audited and bounded; other users receive
  404 rather than data. Contract types are generated from the Pydantic schemas.
- NoteForm now supports `Ctrl+J`, search, one-click insertion, saving the current note
  as a snippet and deleting snippets. Snippets load only when the picker opens, so the
  booking lookup path does not gain an extra request on mount.
- Verification after the change: backend Ruff/contract/unit gate passed (**180 passed,
  162 skipped**); frontend lint/typecheck/Vitest/build passed (**245 tests passed**).

## Supplier classification and interface completion (2026-11-10)

- Agent, QC and Admin can classify individual booking rows and workspace records.
  See the later administration/report-center section for the current per-booking
  override and the separate Admin/QC folder defaults.
- Per-booking classification preserves operational fields and drafts and records
  before/after values in audit logs; sibling monthly bookings retain their own type.
- Completed inline editing, report/ticket/note-search styles, request loading and
  actionable error feedback, filtered administration empty states, and mobile report
  tables. Existing theme tokens and English/Vietnamese copy are used throughout.
- The original UI iteration was verified on Chromium and local TLS MySQL. Its
  verification artifacts are superseded by the current per-booking management/report
  results in `docs/quality/admin-report-center-verification.json`.
- See `docs/supplier-classification-ui.md` for workflow scope and repeatable
  checks. The expanded follow-up below requires migration 0015; no production
  deployment was performed.


## Administrative CRUD, report center and system diagnostics (2026-11-10)

- Added per-booking classification overrides and actions in every booking row and
  workspace for Agent/QC/Admin, including imported unclassified records. Supplier
  folder defaults retain their Admin/QC scope.
- Added a typed Admin data console for twelve business-resource categories, direct
  delete actions in User/Booking/Status screens, selected-record recycling, a unified
  restore/purge bin, dependency previews and durable private-object cleanup retries.
- Retained user/status historical attribution during soft deletion; permanent purge
  checks retained references. Operational roots are excluded consistently from reads,
  search, statistics and reports; cache/index invalidation happens after commit.
- Replaced primary personal/team reporting with a shared filtered report source,
  actual agent participation/daily activity, detailed rows and professional seven-sheet
  Excel/CSV downloads. Legacy daily/invoice/ticket workbooks also receive shared
  streaming styles without loading their entire datasets into memory.
- Added an observed system control room with component readiness, live database probe,
  process/container/disk/pool capacity, workload/job diagnostics and integrity findings.
  Added a plain-language integrity explanation and repaired URL-change remounting that
  discarded active form state.
- Migration 0015 is required before serving this backend/frontend. Production data,
  provider credentials and production deployment were not changed. Current workflow,
  limits and verification are documented in `docs/admin-report-center.md` and the
  accompanying quality verification results.

## Structured tickets and image composition — migration 0016

- Booking tickets support the two issue suggestions (`contract`, `cannot_send_rejection_letters`), server-derived subjects with canonical booking suffixes, required English content, and up to five private images using the existing S3/R2 storage.
- QC/Admin can open full details, copy the subject/body, and combine up to 100 rejection-letter tickets into the agreed TIM Tool text with distinct booking keys in selection order. Combining produces a copyable draft while preserving source tickets and their handling state.
- The optional Vietnamese-to-English helper offers an explicit Google Translate link plus review/apply, or official Google Cloud Translation v2 when `GOOGLE_TRANSLATE_API_KEY` is configured on the backend. No new frontend secret or dependency is required.
- Notes accept image selection and previews before saving. Submitted image batches persist in IndexedDB; the durable outbox checkpoints the saved note and resumes image uploads after network errors/reloads. A failed image batch can be discarded while keeping the saved note. Unsubmitted selected images remain in memory.
- Existing ticket bodies remain readable. Legacy clients can continue to create unclassified tickets; those tickets cannot be included in structured rejection-letter bundles. Language validation is a Vietnamese-character/Latin-text guard, not comprehensive language identification.
- Apply `alembic upgrade head` before API startup. Migration 0016 is additive except for making attachment `note_id` nullable. The current Render AF_Booking service follows `main` with commit auto-deploy and runs `alembic upgrade head` in its start command before uvicorn. Ticket images are retained across recycling and queued for private storage cleanup on permanent removal.

## Administrator tickets and Excel dashboards

- `/admin/tickets` gives Admin a dedicated all-status ticket list with full details/images, editable title/issue/message/status/handling outcome, and recoverable deletion. `PATCH /work-tasks/{id}` enforces Admin authorization and an optimistic content/handling token; edits are audited and do not modify booking notes or booking versions.
- Report-center Excel opens on a branded Visual dashboard with six native chart views, filtered numeric source data and KPI cards. Personal daily, team snapshot and streamed daily-update Excel exports include matching dashboards. Detail tables and CSV data are retained; charts distinguish bookings from updates, preserve category totals and show truthful empty states.
- Uses the existing openpyxl dependency and existing ticket/recycle schema. No new service, secret or migration is needed.
