# Testing

Current Prompt 10 workflow is below. Earlier prompt sections retain their historical
results; they do not replace the current verification record.

## Prompt 10 commands and gates

Verified locally on 04 Nov 2026: **323 passed, 2 optional hosted-probe skips on
each engine** in the coverage run. Services coverage: **92.63% MySQL / 92.57% TiDB**,
with the 80% gate enabled. Separate schema/migration/rollback checks passed on both
engines. Unit-only mode: 180 passed/162 DB-browser skips. Frontend: **245 Vitest
tests**, lint, strict TypeScript, security negative probes and configured production
build passed. **All 13 Chromium scripts passed** in one complete batch.
Python/npm audits report zero known vulnerabilities; no CVE exclusions were used.
Measured load: [before/after report and remaining latency gaps](performance/load-results.md).
The manual load suite currently fails REST/key p95 targets on the shared runner;
its failures are retained.
Raw summaries: [service coverage](quality/service-coverage.json),
[audit metadata](quality/audits/metadata.json). Backup CLI/empty-target recovery and
retention/isolation checks are included in the real-engine coverage counts.
Separate 2,000-folder/50,000-booking search and 50,000-booking integrity
performance checks passed on both engines; raw reports are under
`docs/performance/{search,integrity}-prompt10-{mysql,tidb}.json`.
GitHub Actions execution and hosted-provider probes are not claimed by local checks.


From `backend`, install the committed hash-locked development requirements. Unit
tests deliberately ignore database environment variables; mutating integration
tests run only with the disposable Docker runner. Local MySQL/TiDB use a generated
CA and hostname verification; no hosted account is required.

```sh
mkdir -p /tmp/booking-coverage
COVERAGE_FILE=/tmp/booking-coverage/.coverage .venv/bin/python tests/run_schema_checks.py --engine mysql --suite coverage --report /tmp/coverage-mysql.xml
COVERAGE_FILE=/tmp/booking-coverage/.coverage .venv/bin/python tests/run_schema_checks.py --engine tidb --suite coverage --report /tmp/coverage-tidb.xml
.venv/bin/python tests/run_schema_checks.py --engine mysql --report /tmp/schema-mysql.json
.venv/bin/python tests/run_schema_checks.py --engine tidb --report /tmp/schema-tidb.json
```

Coverage includes all ordinary unit and business database suites, including backup
and observability, and fails below **80% for app/services**. Separate browser,
50k-record performance and schema rollback suites are not included in its denominator.
Use a dedicated directory for COVERAGE_FILE: coverage erases old files with that
prefix; never give it a prefix shared by unrelated logs. Locust
pytest auto-loading is disabled (`-p no:locust`) so its gevent patch cannot change
async application tests; coverage still supports greenlet/thread workers.

`tests/factories.py` provides deterministic account rows; the shared Rig supplies
authenticated HTTPX AsyncClient requests and private disposable data. Unit tests
exercise bounded slow-client sends independently of actual socket scheduling.
Backend and FE key parsing share JSON fixtures and all five resolution states.
Note-history pagination is checked with timestamp ties, deleted rows and multiple
attachments, including a one-note page that must keep every attachment.

From `frontend`, run `npm run lint`, `npm run typecheck`, `npm test`,
`npm run test:security`, `npm audit --audit-level=low` and a configured `npm run build`.
Vitest covers shared key formats, useRequest slow/timeout/cancellation with fake
clocks, realtime My bookings insert/remove, task events/calendar validation, and
NoteForm required-status validation plus synchronous double-submit prevention.
Optional Sentry tests verify disabled initialization and private-data removal.

The separate browser job runs 13 real Chromium scripts with multiple browser
contexts and real FastAPI/TLS TiDB. The task/reminder harness advances its owned
DB clock; it does not add a production test endpoint. Scenario mapping:

| Requested scenarios | Browser scripts |
| --- | --- |
| 1–4: history, locks, takeover, Done/Parking, concurrent conflicts | workspace.mjs, deadlines.mjs |
| 5–8: replaced session, shortcuts, role guards, backend restart/reconnect | smoke.mjs, workspace.mjs, security.mjs, deadlines.mjs |
| 9: due toast, bell, offline catch-up, completion and ownership | tasks.mjs |
| 10: optimistic save, offline queue and UUID replay | outbox.mjs, deadlines.mjs |
| 11–12: typo confirmation and duplicate-note review | safeguards.mjs |
| 13–14: watch merging, assignment auto-completion, palette | collaboration.mjs |
| 15: station/folder/Supplier search and new-folder rules | folders.mjs |
| 16: invoice chips/declaration/standalone edits/search/export | invoices.mjs |
| 17: display/partial keys, mandatory station, exported display keys | folders.mjs, invoices.mjs, admin.mjs |
| 18: actual 8 s lookup deadline/slow/Retry, >15 s withheld note response/replay | deadlines.mjs |
| Additional: daily report, safe note highlighting, PWA updates, CSP/password rotation | operations.mjs, pwa.mjs, security.mjs |

```sh
# From checkout root; omit BOOKING_CHROMIUM_PATH when using Playwright-installed Chromium.
BOOKING_CHROMIUM_PATH=/usr/bin/chromium BOOKING_E2E_ARTIFACTS=/tmp/booking-browser backend/.venv/bin/python backend/tests/run_schema_checks.py --engine tidb --suite frontend --report /tmp/browser.xml
```

The GitHub Actions pipeline runs lint, hash-locked dependency audits, units, MySQL
coverage, both-engine schema/business/performance checks, FE lint/types/Vitest/build
and a separate browser job. Reports/screenshots/coverage are uploaded.
The sequential lookup/scan microbenchmarks raise only their isolated test-app
request limit to allow hundreds of samples from one account. Production rate
limits, abuse tests and the separate 50-user mixed load retain normal defaults.
Large mixed load runs are manual because timing gates need an uncontended runner;
see [load testing](performance/load-testing.md). Encrypted backup scheduling is
opt-in; see [backup and tested recovery](backup.md). Logs, metrics, optional Sentry
and cleanup ages are documented in [observability](observability.md).


Run the backend unit suite from `backend` with `.venv/bin/python -m pytest -q`. Tests verify readiness failure/success, CORS, request cancellation and its elapsed deadline, TLS verification configuration, production restrictions, and database pool configuration. Contract tests also verify UTC millisecond serialization, nullable fields, required display keys, pagination, sanitized validation errors, domain statuses, safe internal errors, and preserved response headers. Two integration tests are skipped unless `TEST_DATABASE_URL` is set; skipped tests are not database validation.

To validate a real TiDB connection, use an isolated test database. Supply connection settings through your terminal's secure environment or a secrets manager; do not paste credentials into commands committed to Git.

- `TEST_DATABASE_URL`: a `mysql+aiomysql` URL for the test database.
- `TEST_DATABASE_SSL_CA`: optional public CA bundle path. System roots are used when absent.

```sh
cd backend
.venv/bin/python -m pytest tests/test_tidb_integration.py -q
```

These integration tests make read-only probes, assert that the negotiated TLS cipher is nonempty, verify the UTC session timezone, and confirm the ASCII binary collation needed by booking keys. They do not exercise business migrations, data writes, or hosted TiDB Cloud networking.

The foundation was checked against a local TiDB v8.5.0 container using `unistore`, loopback-only access, a private test CA, a server certificate with matching IP/hostname, and mandatory TLS. TiDB Cloud uses its own deployment/certificates. Prompt 2 adds a separate mutating schema check and initial migration; see [database-schema.md](database-schema.md).

To test migrations, admin/status seed repeatability, query plans, rollback, and re-migration, run from `backend`:

```sh
.venv/bin/python tests/run_schema_checks.py --engine mysql --report /tmp/explain-mysql.json
.venv/bin/python tests/run_schema_checks.py --engine tidb --report /tmp/explain-tidb.json
```

Docker is required. The runner creates a uniquely named disposable database/container and temporary TLS certificates, then cleans them up. `tests/test_schema_database.py` is skipped during the ordinary unit run unless the runner supplies `SCHEMA_TEST_DATABASE_URL`; this variable explicitly designates a disposable writable database. Never point it at a persistent application database. CI runs this workflow separately for both engines and uploads the reports.

Prompt 3 auth integration checks run separately in fresh databases:

```sh
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite auth --report /tmp/auth-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite auth --report /tmp/auth-tidb.xml
```

These exercise real database transactions through the ASGI auth endpoints, including one-device session replacement, inactive accounts, role guards, cached-session invalidation/TTL, rate-limit aliases, password/logout races, audit rollback, and transport failure. `tests/test_auth_database.py` is skipped without the runner's explicit disposable database configuration. Unit coverage includes JWT signature/expiry/claim validation, hashing cancellation bounds, request IDs, and database-free `/health`. See [auth.md](auth.md) for endpoint contracts, startup configuration, and curl examples.

Frontend checks, from `frontend`:

```sh
npm test
VITE_API_URL=https://api.example.com/api/v1 npm run build
```

Vitest verifies readiness response handling, production URL validation, the visible failed-connection/retry flow, recognized error envelopes, and interpolation of every shared English UI string. The build includes strict Vue/TypeScript checking and route splitting. It uses an example URL only for build validation; use the real Render URL for deployment.

From the checkout root, verify generated wire types with `backend/.venv/bin/python scripts/generate_contract_types.py --check`. Backend schemas are authoritative; regenerate types after intentional schema edits. CI runs this check so stale frontend types cannot pass the workflow.

To update Python locks intentionally, install `uv`, edit `requirements.in` or `requirements-dev.in`, then run:

```sh
uv pip compile requirements.in --generate-hashes --quiet -o requirements.txt
uv pip compile requirements-dev.in --generate-hashes --quiet -c requirements.txt -o requirements-dev.txt
```

Reinstall with hash verification and rerun affected checks. Frontend installation uses the committed `package-lock.json` and `npm ci`.

Prompt 4 adds shared Python/TypeScript booking-key fixtures and cache tests. Real booking API checks use fresh TLS databases:

```sh
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite booking --report /tmp/booking-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite booking --report /tmp/booking-tidb.xml
```

These verify row-lock/version races, original-response UUID replay after later writes and post-commit timeout, required notes, supplier/station/partial-key rules, private takeover notifications/tasks, cursor ties/deleted notes, stale thresholds, zero-query indexed misses, folder invalidation, batch list queries, EXPLAIN point lookup, cancelled rollback/connection discard, pool exhaustion and lock-wait 503. CI runs schema, auth and booking suites for both engines and uploads reports. Full startup/curl/configuration: [bookings.md](bookings.md).

Verification for the Prompt 4 implementation: **87 backend unit tests passed**; 44 integration tests were skipped in that ordinary run and executed separately where applicable. On **each** disposable MySQL 8.0 / TiDB 8.5 database, **25 booking tests + 16 auth tests + 1 schema/migration/EXPLAIN test passed**. Frontend: **48 Vitest tests passed**, strict type checking and production build passed. Ruff checks/format and generated-contract drift checks passed. The two optional hosted-TiDB probe tests remain skipped because no hosted test connection was supplied; local Docker results do not prove hosted deployment readiness.

Prompt 4B adds classification/index/limiter unit tests and real folder/search/station suites:

```sh
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite folder --report /tmp/folder-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite folder --report /tmp/folder-tidb.xml
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite search-performance --report /tmp/search-mysql.json
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite search-performance --report /tmp/search-tidb.json
```

Folder tests verify all result variants, exact CW versus prefix, all-month ordering/backfills, counts, station/type pagination, accent/punctuation/multiple-word matching, ranking and immediate rename/audit/ACL, TTL/ETag/304/auth, zero-folder stations, no-LIKE key branches, one-query page aggregates, rate limits, and the separate DB deadline. The benchmark creates 2,000 folders/50,000 bookings and checks index plans and warm sequential ASGI p95 below 100 ms. Committed reports and measurement limits are in [folder-search.md](folder-search.md). The post-commit retry test now expires its HTTP deadline after the broadcast hook is reached, so it tests the intended committed-write race without assuming a contended TLS transaction will finish within 100 ms.

Prompt 4B verification: **114 backend unit tests passed** (66 database tests skipped in that unit run). Separate disposable MySQL and TiDB runs each passed **21 folder/search/station tests, 25 booking tests, 16 auth tests and one 2,000-folder/50,000-booking performance/index-plan test**. Frontend remained at **48 passing tests**, strict TypeScript and production build passed. Ruff and generated-contract checks passed. Hosted provider probes remain unrun without an explicit hosted test connection.

Prompt 5 adds realtime manager/lease/scheduler/token-redaction unit checks and real TCP WebSocket peers:

```sh
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite realtime --report /tmp/realtime-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite realtime --report /tmp/realtime-tidb.xml
```

These use the installed Uvicorn `websockets-sansio` backend on a loopback-only listener and the same isolated verified-TLS databases. They verify two-user post-commit updates and fresh lookup, private takeover/stale events, advisory denial/save/expiry/disconnect, same-SID replacement, new login and revocation helpers, actual 4401 close codes, fresh-row handshake checks, JSON ping/pong/idle close, invalid/binary/oversize messages, no duplicate replay events, stale thresholds/batch markers and immediate scheduler catch-up. The ordinary DB fixtures explicitly disable background jobs for isolation; the catch-up test starts the registered scheduler and observes its immediate event. Unit tests separately simulate a permanently blocked sender, bounded queue overflow, SID targeting and failure isolation. These tests establish local protocol/transaction behavior, not hosted Render WSS readiness. See [ws-protocol.md](ws-protocol.md).

Prompt 5 verification: **122 backend unit tests passed**, with 86 database tests skipped in that ordinary run. Separate disposable MySQL and TiDB runs each passed **20 real WebSocket/stale tests, 25 booking regressions and 16 auth regressions**. Frontend: **48 tests**, strict types and production build passed. Ruff/format and generated frame/type drift checks passed. No new migration or dependency lock change was needed. Hosted WSS/provider probes remain unrun without a configured hosted deployment.

## Prompt 6 frontend and real browser checks

From `frontend`, run `npm test` and a configured `npm run build` as above. Vitest
covers abort/late-result races, hard deadlines and GET-only retries, bearer/session
interceptors, guards/canonical routes, scoped keyboard bindings, notification races,
themes, DST formatting, section error boundaries and route/visibility watchdogs.

The browser suite starts the actual Vue dev server and Uvicorn against an owned,
verified-TLS disposable TiDB database. It uses generated test accounts/passwords
without a production test endpoint. From the checkout root:

```sh
cd frontend
npx playwright install --with-deps chromium
cd ..
BOOKING_E2E_ARTIFACTS=/tmp/booking-browser \
backend/.venv/bin/python backend/tests/run_schema_checks.py \
  --engine tidb --suite frontend --report /tmp/browser.xml
```

For an already installed system Chromium, set `BOOKING_CHROMIUM_PATH` to its executable
path instead of installing Playwright's browser. The harness owns port 5173 and requires
it to be free. It stops only its own servers/container. Screenshots go to the requested
artifact directory; generated credentials never belong in screenshots or logs.

The flow checks actual login failure/success, Agent/QC/Admin navigation, protected
routes, persisted dark mode, private takeover notification/read/navigation, display-to-
canonical URL redirects, backend stop/start with automatic WebSocket reconnect plus
notification refresh, second-login force logout, mobile layout/popover fit, and logout.
Browser errors fail the test. GitHub Actions runs this in a separate browser job and
uploads its JUnit report and screenshots. It does not use a hosted TiDB account or
establish live Vercel/Render readiness.

Latest Prompt 6 local verification: **88 frontend Vitest tests passed**, strict
Vue/TypeScript and the production build passed, and **122 backend unit tests passed**.
The ordinary backend run skipped 87 database tests; separately, the new **one real
Chromium/TLS TiDB integration test passed** with all flows above. Ruff/format and the
generated-contract check passed. The previous MySQL/TiDB backend suite results remain
historical evidence; this prompt changes no backend application logic or migration.

## Prompt 7 workspace verification

The frontend suite now has **114 passing tests**, including canonical/partial lookup,
manual-retry UUID reuse, version-conflict review, required notes/invoice declaration,
user-scoped draft persistence/expiry/storage failure, list pagination/takeover races,
cache/session invalidation, timezone filters and disposed-view debounce cleanup.
Strict Vue/TypeScript checking and the configured production build passed.

Backend unit verification passed **122 tests**, with **90 database tests skipped** in
that ordinary run. Separately, **27 booking/list/directory tests passed on each of
MySQL and TiDB**, including the expanded text q semantics and bounded authenticated
Agent lookup. Ruff/format and generated-contract checks passed.

The frontend Docker runner now executes **two real Chromium integration flows**.
Both passed against isolated verified-TLS TiDB: the existing login/roles/theme/
notification/reconnect/session replacement flow, and a two-user booking workspace
flow covering advisory locks, takeover movement, retained drafts, conflict review,
offline/reload/discard behavior, new Supplier/station creation, explicit Done invoice
declaration, Summary filter/return URL/cache, targeted row updates and mobile fit.
The backend fixture chooses the script; no production test endpoint was added.

For manual two-browser instructions and implementation boundaries, read
[booking-workspace.md](booking-workspace.md). These local results do not establish a
hosted Vercel/Render/TiDB Cloud deployment or a public-network latency guarantee.

## Prompt 7B reminder verification

**137 frontend tests passed**, including business-day quick dates, DST gaps/overlaps,
dialog date validation and overdue-message edits, UUID retry, task.due validation/
deduplication, stale read suppression, optimistic rollback with concurrent booking
updates, double-click/late-event guards, explicit Notification permission and sound
after interaction. Strict Vue/TypeScript, production build, Ruff/format and generated
contract checks passed. A legacy timeout assertion now checks the positive remaining
budget instead of assuming no millisecond elapses before Axios dispatch.

**124 backend unit tests passed**; 95 database tests were skipped in that ordinary
run. Separately, these suites passed on **each** disposable verified-TLS engine:

| Suite | MySQL | TiDB |
| --- | --- | --- |
| Schema/migration parity, rollback and re-migration to 0003 | 1 | 1 |
| Private tasks, concurrent UUID/limit, profile timezone and due WebSocket delivery | 4 | 4 |
| Auth regression | 16 | 16 |
| Booking/list/directory regression | 27 | 27 |
| Realtime/stale regression | 20 | 20 |

Task cases also verify original creation replay after snooze/completion, editing an
overdue message, owner-only 404, the five-task limit, profile defaults, and once-per-
deadline durable notifications. Reproduce from the checkout root:

```sh
backend/.venv/bin/python backend/tests/run_schema_checks.py --engine mysql --suite tasks --report /tmp/tasks-mysql.xml
backend/.venv/bin/python backend/tests/run_schema_checks.py --engine tidb --suite tasks --report /tmp/tasks-tidb.xml
```

**All three real Chromium flows passed** against isolated TLS TiDB. The additional
`frontend/e2e/tasks.mjs` verifies Alt+T/Enter scheduling, local date/time request bodies,
pending bells, actual private due frames/toasts/title/bell, snooze, login catch-up modal,
completion-to-note focus, Completed view, saved profile defaults, five-task errors,
edit/cancel and mobile fit. Screenshots include `tasks-due.png` and `tasks-mobile.png`.
The isolated stdin test harness advances only its owned test DB clock to avoid waiting
minutes; no production endpoint or test route exists. CI runs all three browser flows
and both task database suites.

```sh
BOOKING_CHROMIUM_PATH=/usr/bin/chromium BOOKING_E2E_ARTIFACTS=/tmp/booking-browser backend/.venv/bin/python backend/tests/run_schema_checks.py --engine tidb --suite frontend --report /tmp/browser.xml
```

Use `BOOKING_CHROMIUM_PATH` only if that executable exists; otherwise use the pinned
Playwright install described above. The runner owns port 5173 and its temporary
processes/container; leave user processes alone. Actual minute-based manual scheduling
and browser-close/reopen instructions are in [tasks.md](tasks.md). Hosted resources
and credentials remain separately configured in Vercel, Render and TiDB Cloud.

## Prompt 7C smart search/folder verification

**174 frontend tests passed**, with strict Vue/TypeScript and production build.
Backend unit verification passed **124 tests**, with **97 database tests skipped**
in that ordinary run; Ruff/format and generated-contract checks passed.
The shared 24-row classifier fixture covers all supplied key/CW/station/Supplier forms,
aliases and invalid shapes. Tests additionally cover cards, breadcrumbs, Escape and
empty-input Backspace, arrow focus, Supplier minimum, 200 ms debounce, stale request
cancellation, slow at 3 s/timeout at 8 s, SWR/LRU bounds, session reset, supplier edits,
targeted realtime hydration and virtual scrolling above 50 months.

Both isolated verified-TLS MySQL and TiDB passed **22 folder/search/station tests**,
including once-per-page aggregation and stale_count parity with month flags/status
thresholds while excluding Done. The 2,000-folder/50,000-booking performance suite passed
on each engine: ten warm query classes, three warmups and 60 measured samples per class.
Maximum class p95 was **18.992 ms MySQL / 49.232 ms TiDB**, below 100 ms. Reports are
[MySQL](performance/search-7c-mysql.json) and [TiDB](performance/search-7c-tidb.json).
They measure local ASGI + TLS loopback DB, excluding public/hosting latency.

The browser runner now executes **four Chromium flows**; all four passed against
isolated TLS TiDB. The new `folders.mjs` covers station/type groups, keyboard selection,
cached breadcrumbs/backtracking, actual booking.updated with targeted folder GET only,
New month supplier reuse, canonical/partial/invalid/station-mismatch keys, new Supplier
guards, station-period rows, Summary filters/deep-link/reload/return URLs, per-user recent
folders, Admin/QC supplier editing and mobile fit. Screenshots include
`folders-summary.png` and `folders-mobile.png`. The original auth/collaboration/task
flows remain in the same CI job. No production test endpoint was added.

```sh
backend/.venv/bin/python backend/tests/run_schema_checks.py --engine mysql --suite folder --report /tmp/folder-mysql.xml
backend/.venv/bin/python backend/tests/run_schema_checks.py --engine tidb --suite folder --report /tmp/folder-tidb.xml
backend/.venv/bin/python backend/tests/run_schema_checks.py --engine mysql --suite search-performance --report /tmp/search-mysql.json
backend/.venv/bin/python backend/tests/run_schema_checks.py --engine tidb --suite search-performance --report /tmp/search-tidb.json
BOOKING_CHROMIUM_PATH=/usr/bin/chromium BOOKING_E2E_ARTIFACTS=/tmp/booking-browser backend/.venv/bin/python backend/tests/run_schema_checks.py --engine tidb --suite frontend --report /tmp/browser.xml
```

No migration or dependency change is required; head remains 0003. Manual checks and
implementation boundaries: [smart-search.md](smart-search.md).

## Prompts 8 and 8B

Backend unit coverage includes safe export cells/business-day DST boundaries, warmup
IP limiting, timing, coalesced versions and the prior authorization/request/cache tests.
The ordinary run passes 135 tests and skips 105 tests that need separately configured
databases/browser services. Skips are not counted as integration passes.

The disposable TLS suites on **each** MySQL 8.0.46 and TiDB 8.5.0 pass:

| Suite | Tests | Main coverage |
| --- | ---: | --- |
| auth | 16 | login, revocation, single SID, ACL and password hashing |
| booking | 27 | canonical keys, notes/version/idempotency, lists and SQL/cache boundaries |
| tasks | 4 | private scheduling/due/snooze/limits and creation replay |
| realtime | 20 | real sockets, locks, private notifications, stale jobs and ordering-independent coalescing |
| folder | 22 | query classification, supplier words/index, folder/station aggregation, ACL/ETag |
| admin | 6 | user self-protection/kick/audit; delete/restore snapshot; dynamic statuses; timezone/columns/CSV/XLSX/formula protection; report/task privacy/profile; status ETag/auth and disconnected export connection invalidation |

Run `tests/run_schema_checks.py --engine mysql --suite admin --report /tmp/admin-mysql.xml`
from backend, repeat with TiDB and a distinct path. No real account credentials are
required: each runner creates its own TLS DB and temporary accounts, then removes its
container. New tests introduce no production test endpoint or default credential.

Frontend Vitest passes 194 tests, including outbox persistence, UUID/backoff/order,
business rollback, user isolation, limits/quota/cancellation; SWR LRU/ETag/old versions;
warmup retries/disposal; Admin self-protection and Profile actions. Production strict
TypeScript/build passes. Generated wire types, Ruff and format checks remain required.

Six Chromium scripts cover authentication/theme/notifications, two-user booking
conflicts/drafts, tasks/alerts, smart folders, Admin/QC/Profile and the durable outbox.
The offline script queues two notes, confirms immediate previews/form clearing/focus,
reloads with a retryable server response, then resumes online with sequential versions
and verifies exactly three historical notes including the original. Admin browser checks
include session kick, user access, delete/restore with realtime, live status labels,
Supplier/Station edits, QC CSV/chart/guards, password change and mobile fit. The browser
runner owns port 5173; do not run two browser suites simultaneously.

For key/index measurements and raw before/after JSON/EXPLAIN use
[performance-8b.md](performance-8b.md). Benchmarks use isolated local databases, not
hosted provider latency. Current schema remains 0003; no new migration was needed.


## Prompt 8C

Current checks pass 143 backend unit tests (115 separately configured integration
cases skipped in that ordinary run), 201 Vitest tests and strict production build.
On EACH disposable TLS MySQL/TiDB, schema parity/downgrade/re-upgrade to 0004 (1),
auth (16), booking (27), folder (22), Admin (6), realtime (20), tasks (4) and safeguards
(8) pass. Old migration files remain unchanged. Shared fixtures explicitly declare
intended repeated/new operations; the safeguard suite tests both confirmation guards
without those overrides. New tests also cover nullable source data, fresh locked
repair, preserved clock/invoices, system scheduling and cancellation/restart.

The 50k-booking/50k-note benchmark checks every booking, limits the sample to 200,
repairs all 250 injected mismatches and measures concurrent lookup; raw data and
reproduction commands are in [safeguards-integrity.md](safeguards-integrity.md).
The browser runner now has seven scripts, adding genuine suggestion-keyboard,
new/duplicate confirmation, status reminder and Admin integrity repair/mobile/ACL
flows. Its corruption command exists only in the disposable test harness.


## Prompt 8D collaboration verification

- **143 backend unit tests passed**, with **124 integration/browser tests skipped**
  by the ordinary run; those skipped counts are not a substitute for database tests.
- On **each** disposable verified-TLS MySQL/TiDB, schema 1, auth 16, booking 27,
  tasks 4, realtime 20, folder 22, Admin 6, safeguards 8 and collaboration 8 passed
  (**112 checks per engine**). The new migration 0005 has model parity and successful
  downgrade/upgrade, including nullable generated unique guards.
- **211 frontend Vitest tests passed**, plus strict TypeScript and production build.
- **All eight real Chromium scripts passed together** against TLS TiDB, including
  three-user watch/merge/assignment completion, palette role/canonical-key behavior,
  typing exclusions, row Task/Watch/Open shortcuts and mobile overflow checks.
- Booking list privacy flags and task counts use one aggregate; the existing four-
  SELECT page budget and no-note-table-read regression stay enforced. No new
  dependencies or old migration edits. Reproducible commands/limits are in
  [collaboration.md](collaboration.md).

## Prompt 8E operations and PWA verification

- **146 backend unit tests passed**; **137 integration/browser cases** are skipped
  in the ordinary run and require the disposable runner below.
- On **each** verified-TLS disposable MySQL 8.0 / TiDB 8.5 database, schema parity,
  downgrade/re-upgrade and EXPLAIN (1), auth (16), booking (27), tasks (4), realtime
  (20), folder (22), Admin (6), safeguards (8), collaboration (8) and operations
  (11) passed: **123 checks per engine**. Head is **0006**; migrations 0001–0005
  remain unchanged. No FULLTEXT index is part of the mandatory migration.
- **223 Vitest tests passed**, with strict Vue/TypeScript and production PWA build.
  Coverage includes visible-only refresh/cancellation, Unicode text highlighting,
  explicit push permission, subscription ownership failure, and draft-safe reload.
- **All ten Chromium scenarios passed together** against disposable TLS TiDB.
  New flows cover Admin-only health/degraded navigation and stopped refresh after
  leaving the page, Vietnamese note search with literal HTML, QC report Excel/print,
  mobile fit, no automatic permission request, and the actual production service
  worker's offline shell, static-only caches, waiting update and explicit Reload.
- Ruff/format, generated API types and dependency consistency checks passed.

Run the new database suite from `backend`:

```sh
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite operations --report /tmp/operations-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite operations --report /tmp/operations-tidb.xml
```

It verifies bounded request counters/slow-query fingerprints without parameters,
daily totals and immutable past JSON/Excel after moderation, 60-second current-day
cache/evening finalization, formula-safe workbook columns/business timezone,
Vietnamese/date-bounded/deleted-note search, actual optional MySQL ngram queries
with Alembic parity, explicit unsupported TiDB FULLTEXT, Admin-only health events,
push IDOR/online suppression/revocation/dead cleanup, queue deduplication, actual
VAPID encryption through an intercepted HTTPS transport, and disconnect-cancelled
export queries with a healthy subsequent pool probe.

The browser command above now runs ten scripts. `pwa.mjs` builds/serves production
Vite locally; its external-looking test API origin is intercepted inside Chromium,
not a real provider request. The update fixture changes ignored `dist/sw.js`; run
a clean production build afterward before serving build artifacts again.
Artifacts include `daily-report-mobile.png`, `daily-report.xlsx` and
`pwa-offline-shell.png`. Never run two browser suites on port 5173 concurrently.

These results do not validate hosted TiDB Cloud networking, real push-provider
delivery, or physical iOS behavior. Live VAPID settings/device permission are needed
for those checks. Historical 50,000-row performance reports were not remeasured for
8E. Configuration and manual verification are in [operations-pwa.md](operations-pwa.md).

## Prompt 8F invoice verification

- **158 backend unit tests passed**, with **147 integration/browser cases skipped**
  during the ordinary run; mutating checks execute separately in owned databases.
- On **each** verified-TLS disposable MySQL/TiDB, migration 0007 parity/seed/EXPLAIN/
  downgrade/re-upgrade (1), auth (16), booking (27), tasks (4), realtime (20),
  folder (22), Admin (6), safeguards (8), collaboration (8), operations (11) and
  invoices (9) passed: **132 checks per engine**. Old migrations remain unchanged.
- **234 Vitest tests passed**, plus strict Vue/TypeScript and production build.
  Coverage includes shared parsing, validation/checkbox/owner controls, +N badges,
  invoice-required Done, persistent PUT replay, chip drafts and 4xx restoration
  without replacing an unfinished note. The storage-quota fixture restores its
  mocked storage getter so later draft checks exercise real persistence.
- **All eleven Chromium scenarios passed together**. The new multi-user invoice
  case covers Done with two numbers, no-note/unchanged-clock additions, owner versus
  QC removal, immediate realtime, adjacent-month duplicate links, INV: search,
  offline PUT/reload/reopen/retry with retained note draft and unchanged Activity,
  monthly Excel, unknown-filter navigation and mobile layout. Existing Report
  assertions explicitly scope performance metrics now that invoice cards coexist.
- Ruff/format and generated-contract checks passed. The production build is
  regenerated after the PWA fixture so dist/sw.js contains no test update marker.

From `backend`, use `tests/run_schema_checks.py --engine mysql --suite invoices
--report /tmp/invoices-mysql.xml`, then repeat with tidb. In addition to JUnit,
the invoice suite writes a sibling `.plans.json` with four actual EXPLAIN cases.
Copies and interpretation are in [invoices.md](invoices.md); the tiny fixture does
not establish hosted performance. The preview budget asserts exactly one invoice
query for 20 booking rows; the reconciliation budget asserts one bookings-only
aggregate, without joins. No new 50,000-row benchmark or hosted deployment is
claimed. Browser commands/artifact paths follow the existing runner above.


## Prompt 9 security verification

On 04 Nov 2026, **174 backend unit tests passed**, with **153** DB/browser checks
skipped in the unit-only run and exercised separately where applicable. **240
Vitest tests passed**. Clean npm ci, strict TypeScript, production build with
VERCEL=1 and matching example HTTPS/WSS CSP, Ruff/format, generated contract parity,
whole-frontend ESLint and negative v-html/CSP mismatch probes passed.

On **each** disposable verified-TLS MySQL/TiDB: auth 16, booking 27, tasks 4, Admin
6, safeguards 8, collaboration 8, operations 11, invoice 9, realtime 20, folder 22
and new hardening 5 = **136 business tests**, plus **one full schema/migration/seed/
EXPLAIN/downgrade/re-upgrade test** through additive migration 0008: **137 per engine**.
The query-cancellation fixture warms its TLS pool outside a 500 ms deadline and
still cancels a two-second query, verifies invalidation and a healthy subsequent
connection; cold setup is not confused with the intentional slow query.

**Twelve Chromium scenarios were verified**: eleven existing scripts passed in the
batch, and the new security script passed on its targeted rerun after correcting
socket accounting for Vite development traffic and Playwright page destruction.
It asserts one active application socket, one held Web Lock and one waiting
follower, leader-close handoff, shared logout/token removal, and required password
rotation without a business socket. The production PWA scenario checks the actual
CSP response, blocks injected inline script, has no inline boot script, and verifies
static-only caching/offline/update behavior. No failed assertion was disabled.

pip-audit 2.10.1 against the entire hash-locked dev/runtime dependency graph and
npm audit against the full lockfile both returned **zero known findings**, without
CVE exclusions. npm audit initially identified six affected frontend packages;
pinned tooling/transitive overrides removed them. [Audit JSON and verification
summary](security/) include lockfile SHA-256 values. FastAPI ORJSONResponse and
Starlette TestClient deprecation warnings remain non-security maintenance notes.

The new suite uses `tests/run_schema_checks.py --engine mysql --suite security
--report /tmp/security-mysql.xml` from backend; repeat with tidb. Existing disposable
runner/browser commands above apply. CI now runs both-engine hardening, audits,
security lint and the twelfth browser script. Live hosting, actual provider push,
physical iOS behavior and 50,000-row benchmarks were not revalidated in this step.
Production configuration/limitations are recorded in [security-report.md](security-report.md).
