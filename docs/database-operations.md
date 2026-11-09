# Database operations and query guide

This runbook is the operator/AI starting point for database changes in AF Booking. It describes the checked-in implementation, not a claim that production provider limits or latency have been measured. For the authoritative table definitions and migration process see [database-schema.md](database-schema.md); for deployment settings see [deploy.md](deploy.md); for reproducible tests see [testing.md](testing.md); for measured load limitations see [performance/load-results.md](performance/load-results.md).

## Runtime topology and connection budget

The backend uses SQLAlchemy 2 async with `mysql+aiomysql`, TLS certificate and hostname verification, `READ COMMITTED` by default, and an async queue pool. The current safe baseline is one Render instance and one Uvicorn worker: auth/session invalidation, realtime, scheduler, locks, and several caches are process-local. Do not scale workers or replicas just to add DB concurrency until those stateful components are shared or their consistency limitations have been accepted.

Current settings (`backend/app/core/config.py`, `backend/app/core/db.py`):

| Setting | Default | Purpose |
| --- | ---: | --- |
| `DB_POOL_SIZE` | 5 | Persistent pooled connections per process |
| `DB_MAX_OVERFLOW` | 0 | Temporary extra connections; total is validated to at most 10 per process |
| `DB_POOL_TIMEOUT_SECONDS` | 5 s | Maximum wait to acquire a connection |
| `DB_CONNECT_TIMEOUT_SECONDS` | 5 s | Driver connect and bounded readiness probe budget |
| `DB_POOL_RECYCLE_SECONDS` | 280 s | Recycle an aged connection on next checkout |
| `DB_QUERY_TIMEOUT_MS` | 5,000 ms | MySQL/MariaDB session execution timeout where supported |
| `DB_LOCK_WAIT_TIMEOUT_SECONDS` | 5 s | Session lock wait limit |
| `REQUEST_TIMEOUT_SECONDS` | 8 s | HTTP request budget; route-specific budgets may be shorter |

Size the pool from the *database's application connection budget*, not the web service's desired concurrency:

```text
max possible app connections = instances × workers × (pool_size + max_overflow)
```

Reserve database connections for migrations, provider administration, backup/monitoring, and failover/rolling deploy overlap. Confirm TiDB's actual plan/connection ceiling and the Render instance/worker count before changing values. `DB_POOL_SIZE=5` is the measured starting point, not a universal optimum. Increasing pool size can increase concurrent database work and worsen queueing/CPU latency; the current shared-runner load results do not establish a production pool optimum.

### Pool tuning procedure

1. Keep one instance and one worker. Record the time window, deployed commit, actual TiDB cluster/region, instance size, and request mix.
2. Observe Admin → System Health (pool `size`, `checked_out`, `overflow`; request percentiles; DB probe latency) alongside provider-side active connections, CPU, memory, query latency, and throttling. These application counters are per-process and reset on restart.
3. Diagnose saturation: sustained `checked_out` near pool capacity plus increased acquisition time/503 suggests pool queueing; low checked-out with slow requests points toward SQL plans, database/network latency, or application work instead. A low pool count alone is not a reason to raise the cap.
4. Change only one knob at a time. Keep the configured total under both the repository's 10/process safety bound and the provider budget after multiplying by overlap/instances/workers. Use modest steps (for example, 5 → 6 only if measurements show pool wait and DB headroom), then rerun the same isolated 50-user workload and compare p50/p95/p99, errors, active connections, CPU, and query plans.
5. Revert if tail latency, provider saturation, or errors worsen. Never adjust production pool size based only on a synthetic local container or a one-off average.

`pool_pre_ping` validates stale connections at checkout; recycle is age-based and not an idle-time guarantee. Do not disable verified TLS, bounded timeouts, or safe connection invalidation to reduce a few milliseconds. Keep secrets out of diagnostics and repository files.

## Query path and data access rules

- Models and constraints: `backend/app/models/entities.py`; migrations: `backend/alembic/versions/`. Treat migrations as append-only. Do not edit an already released migration to repair a live schema.
- API and validation: `backend/app/api/v1/` and `backend/app/schemas/`; query/business logic: `backend/app/services/`.
- Transactions and database deadlines: `backend/app/core/unit_of_work.py`, `backend/app/core/timeouts.py`, and `backend/app/core/db.py`. Keep read/write sets bounded and do not hold a transaction open during network calls, WebSocket sends, or response encoding.
- Use explicit joins/preloads. Lazy ORM relationship reads are not the project pattern. Paginated child reads should limit parent/ID rows before loading attachments or other one-to-many details; otherwise a join can multiply page rows or force a broad scan.
- Store/compare instants in UTC (`DATETIME(3)`); convert business-day boundaries using `BUSINESS_TIMEZONE` before querying. Preserve binary ASCII booking-key comparisons and existing soft-delete/ownership predicates.
- New sort orders must be deterministic: add a unique tie-breaker (normally the numeric `id`). An index should match the equality/filter prefix followed by ordered columns; validate actual plans on both disposable MySQL and TiDB before adding it.
- Avoid `SELECT *`, unbounded reads, N+1 loops, unbounded `IN` lists, and per-row correlated queries for reports. Batch aggregates and bound payloads. Use streaming for exports and report paths already designed for large results.
- Do not emit SQL text, bind parameters, `DATABASE_URL`, notes, credentials, or user data in logs. Current slow-query telemetry stores a normalized fingerprint and duration only.

### Safe production diagnostics

Start with the Admin system-health view and provider dashboard; compare them over the same time interval. For a query-plan investigation, reproduce the shape against a sanitized disposable database with representative row counts, then use `EXPLAIN` (and provider-supported `EXPLAIN ANALYZE` only when safe). Check chosen index, estimated/actual rows, extra sort/temp operators, and whether the plan changes with selectivity. The project's disposable plan checks are:

```sh
cd backend
.venv/bin/python tests/run_schema_checks.py --engine mysql --report /tmp/explain-mysql.json
.venv/bin/python tests/run_schema_checks.py --engine tidb --report /tmp/explain-tidb.json
```

These use fresh local containers and test data; they do not connect to the production database or prove production latency. Never run `ANALYZE TABLE`, DDL, bulk updates/deletes, or explain-analyze against production without reviewing provider impact, permissions, and an approved maintenance procedure. Do not paste production rows or secrets into tickets or AI prompts.

The latest source-level SQL review is [index-review-2026-11.md](performance/index-review-2026-11.md). Migration `0011` adds `(user_id, created_at, id)` for the notification feed and `(user_id, status, completed_at, id)` for completed-task ordering. The report separates these two chosen changes from other candidates that need actual production plans or a query rewrite first. Treat its synthetic plan gates as optimizer-path checks, not production latency evidence.

## Pagination status and keyset migration plan

The repository already uses keyset pagination for booking-note history (`GET /bookings/{key}/notes`), with an opaque cursor tied to the booking and a `(created_at, id)` order. That is the working local example. The remaining list APIs currently use numbered pages, return exact `total`, and are consumed by numbered `PageControls` that support page jumps and last-page recovery. Replacing their SQL alone would break the API contract/UI; keeping numbered arbitrary-page navigation requires an offset (or a cursor chain/cache and extra state), and retaining exact total still pays for the separate count query. There is therefore no safe transparent “replace `.offset()` only” change.

Current `OFFSET` query inventory (`rg -n '\.offset\(' backend/app/services`):

| Service | Endpoint/data | Existing order | Cursor tuple candidate |
| --- | --- | --- | --- |
| `booking_reads.py` | `/bookings`, `/bookings/mine`, `/bookings/stale`, watching | `updated_at` + `id`, ascending or descending | `(updated_at, id)` with direction-specific lexicographic predicate; bind cursor to filters, owner/scope, and sort |
| `tasks.py` | `/tasks` pending/due/done | `(remind_at,id)` ascending; done `(completed_at,id)` descending | Same tuples; decide policy for legacy done rows with NULL `completed_at`; preserve fixed due-time boundary |
| `note_search.py` | `/search/notes` | representative matching note `(created_at,id)` descending | Cursor must be applied after per-booking representative/grouping; verify selected-row ordering matches grouped representative |
| `folders.py` | `/folders` | `(last_activity_at,id)` descending, with ranked supplier-search branch | Cursor includes rank score then activity and ID in ranked branch; keep index and DB fallback ordering identical |
| `folders.py` | station/month bookings | `id` descending | `id` |
| `folders.py` | invoice search | `updated_at,id` descending | `(updated_at,id)` |
| `admin.py` | users | `id` ascending | `id`; cursor must bind to the active substring query |
| `admin.py` | audit | `created_at,id` descending | `(created_at,id)` with all audit filters |
| `admin.py` | booking notes/trash | note `id` descending | `id`, preserving booking/trash/search filters |
| `admin.py` | stations | `Station.code` ascending, grouped folder count | `code`, applied after station aggregation |
| `collaboration.py` | assignments | `created_at,id` descending | `(created_at,id)`, bound to user direction/status |
| `integrity.py` | integrity history | `started_at,id` descending | `(started_at,id)`; keep recovery side effect before listing |

Safe phased cutover for a future breaking pagination migration:

1. Agree that the UI changes from arbitrary numbered pages to next/previous cursor navigation and decide whether exact `total` remains. Keep page-number endpoints until all clients are migrated.
2. Standardize a cursor contract: `{items, next_cursor}` (and optionally `has_more`); fetch `size + 1`; cursor contains the complete sort tuple, direction, and a hash of normalized filters/scope. Reject malformed, tampered, expired, or mismatched tokens. Never trust client-supplied user scope; derive ownership from auth on each request. Do not use a cursor as authorization.
3. Define concurrency semantics. Keyset prevents shifts caused by rows inserted before an offset, but it is not a snapshot: mutable `updated_at`, task reminder dates/status, folder activity, or changing filters can still move records across a cursor. State whether traversal is a live feed or implement a reviewed high-water/snapshot rule.
4. Add matching composite indexes only where EXPLAIN shows a gap and write/storage cost is acceptable. Validate tie timestamps, null handling, each filter/sort, cursor tampering/mismatch, deletions, insertions, and mutations between pages on both MySQL and TiDB.
5. Migrate each frontend store/view and all generated API types/tests. Remove numbered-page support only after searching API clients, E2E scripts, exports, and external consumers. Then remove the old offset path and assert no `.offset(` remains except a documented exception.

Do not claim the application has been fully converted while any route still accepts numbered pages or emits `Page.total/page`. Re-run `rg -n '\.offset\(' backend/app/services` and document any remaining compatibility path in the change summary.

## Release and recovery checklist

Before an application release:

- Confirm a tested backup/recovery path and migration rollback impact; Alembic downgrade can be destructive depending on revision.
- Review the new migration SQL and index build/lock characteristics for the actual database version/provider.
- Apply `alembic upgrade head` once as a release step, not in every worker startup; run `alembic current` and `alembic check`.
- Deploy one worker/instance, verify `/health`, `/api/v1/ready`, `/health/db`, a real authenticated read/write workflow, TLS, and Admin system health.
- Watch errors, slow fingerprints, DB latency, pool saturation, provider connections/CPU, and query plans during rollout. Keep the previous deploy/restore procedure available.
- Distinguish local tests from hosted evidence. The current committed load report explicitly records misses against REST/key p95 goals and says Render/TiDB Cloud has not been measured; use [load-results.md](performance/load-results.md) as the baseline, not as a production SLA.
