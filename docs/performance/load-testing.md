# Prompt 10 load tests

The reproducible harness uses Locust 2.47, a real Uvicorn process and disposable
verified-TLS MySQL 8.0 or TiDB 8.5 (local unistore). It seeds 50,000 bookings,
250,000 notes, 50 acting users, 2,000 supplier folders, 40 stations and 12,500
invoices. Fifty extra observation-only accounts allow 100 real WebSocket peers
while preserving one connection per account. The dataset is synthetic.

From `backend`, with Docker and the hash-locked development requirements installed:

```sh
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite load --report /tmp/load-mysql.json
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite load --report /tmp/load-tidb.json
```

GitHub Actions also exposes `Disposable load benchmark` as a manual workflow.
Its threshold failures remain visible and its measured report is uploaded even on
failure. Shared-runner timing is not directly comparable to this local machine.

Each run owns and cleans up its container, database, API and load processes. It
uses 50 concurrent actors, a 0.4–0.8 second think time, 60-second mixed and key-only
phases, and excludes the first ten seconds of each phase from latency samples.
The mixed weights are 65% lookup, 15% save, 15% My bookings and 5% note search or
permitted daily report. Writes use distinct actor-owned bookings and immutable
UUIDs on retry, avoiding intentional conflicts in this throughput measurement.
The key phase rotates full, formatted, partial and absent keys across the dataset;
it records client and Server-Timing percentiles separately.

A TLS-preserving TCP proxy then adds two seconds of latency per direction. Twelve
uncached requests must return a sanitized timeout/busy error, then DB probes and
lookups must recover after latency is removed. Other tests exercise discarded
connections, pool exhaustion/Retry-After, UUID replay and isolated slow WS senders.
Broadcast latency is measured from committed UTC update time to receipt, including
queue delay; a separate probe must reach all 100 peers.

The harness fails when measured REST p50 >=100 ms, p95 >=300 ms, any key-group
server p95 >=50 ms, broadcast p95 >=500 ms, unexpected HTTP errors, missing peers,
or failed recovery occur. JSON evidence is saved before the final threshold check.
Do not run builds, browser suites or other load tests alongside a measured run.
One API worker, pool size 5, local proxy/TLS, disabled background scheduler and
machine cgroup limits are recorded. Results are local capacity evidence; TiDB
Cloud networking and Render free-tier CPU/cold starts need a deployed rerun.

## Standalone seed and Locust

`python -m app.scripts.seed_load --help` creates the same synthetic data in an
empty migrated database explicitly named `booking_load_*_test`. Supply
`DATABASE_URL` and `LOAD_TEST_PASSWORD` through protected environment values.
The script rejects application databases and analyzes test-table statistics after
bulk insertion. Never run it against production.

`locust -f scripts/locustfile.py --headless -u 50 -r 10 -t 60s --host <test-api>`
is available for an isolated externally managed test environment. It requires a private `LOAD_TOKEN_FILE` (tokens, canonical keys, initial_version
and today), plus `LOAD_RESULT_FILE`, using session tokens obtained from that test API. The bundled harness creates/removes these files automatically;
using `--suite load` is the complete reproducible workflow. Do not put credentials
in manifests, command arguments, artifacts or committed files.

## Optimization and evidence

The initial MySQL mixed run exposed two request timeouts and p95 2,314 ms.
Daily-report invoice totals used correlated lookups for every booking; a large
report serialization blocked the event loop. Grouped invoice aggregation,
streamed report rows, cooperative serialization, cached gzip bytes and a live-note
covering index preserve the complete response while removing this repeated work.
Lookup now uses one transaction, combines private task/watch reads and the cold
snapshot/invoice read, and bounds history before joining attachments. Note search
materializes its ordered page before display joins so the optimizer cannot join
all historical notes before LIMIT. Pool defaults avoid redundant isolation SETs.

Raw before/after JSON and the measured comparison are in
[load-results.md](load-results.md), including the current unmet latency targets. `latest_before` is a diagnostic EXPLAIN with the new
covering index explicitly ignored; `latest_after` is the same aggregate with the
index available. It is an access-path comparison on the final dataset, not a
second pre-change latency run. The actual earlier mixed latency baseline is
retained separately, including its failures. No percentile was inferred for
phases that baseline did not reach.
