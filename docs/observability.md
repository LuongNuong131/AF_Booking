# Logs, health and retention

The API emits JSON logs with UTC timestamp, level, logger, event, request ID,
authenticated user ID when known, method, route template, status and duration.
`http.request` records completion; request IDs are returned to clients. Authentication
sets the user ID in the request scope. Unknown identities are null. Access logging
is disabled in the documented Uvicorn command, preventing WebSocket query tokens
from appearing in ordinary access logs. HTTP client debug logs are suppressed.
Passwords, tokens, note text, SQL parameters and exception traces are not emitted
by the application formatter. Unexpected client errors remain generic envelopes.

`sql.slow` warns above `SLOW_QUERY_THRESHOLD_MS` (default 200), retaining only a
normalized SHA-256 fingerprint and duration. Warnings for the same fingerprint
are throttled for 30 seconds. The Admin page retains the top 20 per hour without
SQL text or bound values. Query plans in benchmark artifacts are synthetic test
data, produced separately by the load harness.

`system.error_spike` warns when REQUEST_TIMEOUT/504 or SERVICE_BUSY/503 counts reach
`ERROR_ALERT_THRESHOLD` (10) in `ERROR_ALERT_WINDOW_SECONDS` (60). Repeated warnings
are throttled by `ERROR_ALERT_COOLDOWN_SECONDS` (60). Counters use bounded per-second
buckets. Forward stdout JSON to your provider's log service to configure external
alerts; a local log warning alone does not send an email or page anyone.

## Endpoints and Admin page

- `/health` and `/api/v1/health`: public, database-free liveness.
- `/health/db` and `/api/v1/health/db`: public, bounded DB probe; shared IP limit
  10/minute, generic failure without connection details.
- `/api/v1/ready`: configured database readiness.
- `/api/v1/admin/system/health`: Admin only. Existing request histograms, database
  latency/pool, WebSockets, locks, scheduler state and sparkline are supplemented
  by `operational_errors`, `key_index` and `snapshot_cache`.

`key_index.container_bytes` is the shallow dictionary storage size, not the full
Python heap or process RSS. Cache hit/miss counts are lifetime counters and reset
on restart. Histograms approximate percentiles; measured load reports use raw
per-request samples. All telemetry is ephemeral and belongs to one API process.
Use exactly one instance/worker until shared sessions/locks/pubsub move to Redis.
The Admin view refreshes only while open and visible.

## Optional Sentry

Backend `SENTRY_DSN` and frontend `VITE_SENTRY_DSN` are independent, blank by default.
No SDK is initialized when absent. Use an HTTPS project DSN. This implementation
disables default integrations/tracing/PII, and scrubs events to error type, generic
message and source-frame locations only. Requests, local variables, breadcrumbs,
user details and note contents are discarded. Frontend Vue and global exception
handlers use the same scrubber. Delivery to a real Sentry project was not exercised.

For frontend deployment, run `npm run configure:csp` with the same `VITE_API_URL`,
optional `VITE_WS_URL` and `VITE_SENTRY_DSN` used for the build. CSP adds only the
specific Sentry origin to connect-src; the Vercel production mismatch guard still
checks the final committed header. See [deploy.md](deploy.md).

## Retention

The independent `data.retention` scheduler job runs at startup and every 24 hours.
It deletes audit logs older than 180 days, notifications **read** more than 60 days
ago, and completed/cancelled tasks last updated more than 90 days ago. Pending
tasks and unread notifications remain. Notification task references are detached
before removing old tasks. Batches default to 1,000 rows, at most 100 batches per category/run,
with short yields; remaining rows wait for the next run. Each batch commits
separately. No migration deletes existing data.

Settings: `RETENTION_ENABLED`, `AUDIT_RETENTION_DAYS`, `NOTIFICATION_RETENTION_DAYS`,
`TASK_RETENTION_DAYS`, `RETENTION_INTERVAL_SECONDS`, `RETENTION_BATCH_SIZE` and
`RETENTION_MAX_BATCHES`. `SCHEDULER_ENABLED=false` disables every background job.
A sleeping free-tier server runs catch-up when it wakes. Migration 0009 adds
retention indexes and a covering index for live-note report aggregation.

The owned SQLAlchemy pool defaults to READ COMMITTED. Explicit REPEATABLE READ
transactions for reporting/backup retain consistent snapshots and restore the
pool default on exit. Cancellation still invalidates the affected connection.
