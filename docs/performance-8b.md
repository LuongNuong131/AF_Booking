# Responsiveness and durable note outbox (Prompt 8B)

## Sending and recovery

Save validates locally, persists an outbox entry, adds a dimmed note/snapshot and
My bookings preview, clears the form and focuses search immediately. An explicit
Sending/Unsent tag separates local previews from committed notes. Browser storage
failure or the 50-entry limit leaves the form intact. Entries are scoped to user ID;
no access token or password is stored with them. Sign-out stops owned requests and
retains that user's unsent notes for their next login. Corrupt queues are retained
in storage and new saves fail closed rather than overwriting their contents.

A single application-owned worker preserves per-booking order across navigation.
Network errors, 429, 5xx, `REQUEST_TIMEOUT` and `SERVICE_BUSY` retry at 2/5/15/30 seconds
(and then 30 seconds), honoring a longer Retry-After. Online/reconnect can resume
sooner. Each retry uses the identical payload and UUID. A following unattempted note
receives its predecessor's committed version; an attempted payload is never rewritten.
The backend's durable UUID replay handles a committed response lost in transit. An older replay after moderation refreshes history instead of restoring a deleted note.

Business 4xx/409 errors stop automatic retries, remove that operation's preview and
return its text to an empty active form. Version conflicts open review with the latest
history. If a different draft is being edited, the blocked operation remains accessible
from the `N unsent` header panel. Review first requires finishing/discarding that draft.
Admin mutations wait for the server. Tasks and read notifications optimistically update
and roll back on errors; a new notification during mark-all remains unread.

The outbox requires an open authenticated tab to transmit. localStorage survives reload;
it is neither a service worker nor background delivery after the browser is closed.
Use one active editing tab per account: single-device session enforcement and one active
WebSocket prevent two independent live editors. Multi-tab collaborative outbox merging
is not implemented; the server still deduplicates identical UUID retries.

## Reads, warmup and rendering

Login starts a nonblocking public `/health/warm` request (45-second deadline, up to six
attempts, five seconds apart) and shows Waking up the server… / Ready. The backend
limits it to 10/minute/IP and runs SELECT 1. `/health` remains DB-free. Login bootstrap
starts auth/me, statuses, mine page 1, due tasks and notifications together.

The shared key parser drives the 150 ms lookup prefetch; other queries debounce 200 ms.
Enter shares an in-flight lookup or reuses its result for 10 seconds. The request cache
holds 50 LRU entries; booking/list freshness is 30 seconds. Opening cached lookup data
renders it before refreshing expired data. Realtime patches matching snapshots, ignores
old versions and refreshes their history; live list components write reconciled pages
back to cache for return navigation. Membership/filter changes invalidate uncertain
pages. Statuses use localStorage, private max-age 60 and ETag/304 with authentication.

Summary-row hover/focus after 150 ms preloads lookup/detail code. Summary route code is
preloaded during idle time. Routes and Admin/chart code load lazily, Element Plus imports
are per component, and Inter is a bundled OFL font with swap/preload. Hashed assets have
one-year immutable caching. Vite injects API preconnect/dns-prefetch; requests go directly
to Render, with no Vercel API proxy. Render Blueprint region is Singapore. A sleeping
free instance still has a real cold start; immediate previews avoid blocking note entry
while it wakes, but do not imply the note is already committed.

Timelines switch to measured variable-height virtualization after 50 rows. Tables have
a virtual window beyond 50; normal summary pages remain 20 rows. Large timeline/My
bookings state is shallow, table rows use v-memo, and booking frames render once per
animation frame. Backend booking events coalesce per key for 100 ms, keeping the newest
version. Personal HTTP responses default to no-store; the status/station catalogues
keep their explicit private policies. GZip starts at 500 bytes and ORJSON is the default
response class (typed responses use FastAPI's native Pydantic serialization).

`Server-Timing` includes total time to headers and completed DB cursor time on HTTP
responses, retaining lookup phase timings. This excludes TLS/network/pool-wait and
stream work after headers; request logs measure completion separately. The dev-only
performance panel shows recent timing headers and received event count. Password hashing
uses bounded `run_in_threadpool` jobs whose slots remain occupied until cancelled work
actually finishes. DB I/O stays asynchronous with pre-ping and finite query budgets.

## Measurement and reproduction

The accompanying `docs/performance/responsiveness-{mysql,tidb}.json` files compare the
same warm lookup worker against commit `d640d851a6221a8e7ccef92215b0a11e0efb7096`
and this implementation. Both use 2,000 folders / 50,000 bookings in a disposable
verified-TLS loopback database, three warmups and 60 samples per query. These are local
ASGI measurements, excluding public Render/Vercel/TiDB Cloud network latency and cold
starts. p99 is the highest of 60 samples, not a long production percentile estimate.

To reproduce from repository root:

```sh
mkdir -p /tmp/booking-lookup-baseline
git archive d640d851a6221a8e7ccef92215b0a11e0efb7096 backend | tar -x -C /tmp/booking-lookup-baseline
BOOKING_LOOKUP_BASELINE_ROOT=/tmp/booking-lookup-baseline/backend backend/.venv/bin/python backend/tests/run_schema_checks.py --engine tidb --suite search-performance --report /tmp/responsiveness-tidb.json
```

Omit the baseline variable to measure current code only. The JSON also includes full
EXPLAIN output, cache hit ratio/capacity/TTL, index retained-size estimate and bootstrap
time. Run benchmarks without concurrent browser builds or other database suites.
A loaded run exceeded the search budget; the isolated rerun and its raw measurements
are retained in the report below. Measurements should be repeated on the chosen hosted
plan before claiming an end-to-end latency target.

| Lookup group | MySQL before p95 | MySQL after p95 | TiDB before p95 | TiDB after p95 |
| --- | ---: | ---: | ---: | ---: |
| Existing full key | 7.592 ms | 8.09 ms | 9.694 ms | 12.811 ms |
| Missing full key | 0.968 ms | 1.369 ms | 0.993 ms | 1.215 ms |
| Partial key | 6.376 ms | 7.248 ms | 13.71 ms | 14.79 ms |
| Spaced full key | 7.508 ms | 9.679 ms | 12.19 ms | 14.006 ms |

The new timing/compression path adds roughly 0.2–3.1 ms in these small-response samples;
it does not improve server lookup p95. All four groups remain below 15 ms here. The main
perceived improvement is immediate local Save and eliminating duplicate/navigation
requests, verified by the offline/reload browser test. Search max p95 was 26.632 ms on
MySQL and 69.176 ms on TiDB (target <100 ms).

The shared index retains approximately 33,524,394 bytes (32 MiB), including shared
strings counted once; this is a Python object-graph estimate, not process RSS. Bootstrap
was 933 ms on MySQL / 1,033 ms on TiDB. Warm snapshot hit rate was 188/189 (99.47%) in the
repeated-key workload. Keep TTL 30 seconds and capacity 2,000: enlarging this to every
booking would spend memory without improving the measured warm workload. Measure
production key distribution before changing these bounds.

MySQL plans show full-key `const` on the unique key and partial-key `ref` on
`ix_bookings_cw_period`; TiDB uses indexed point/range operators instead of MySQL type
names. Summary uses `ix_bookings_updated_at` and `ix_bookings_agent_updated`; no additional
wide covering index is justified for the 10/20-row pages measured here. Lists select
snapshot columns/preview only and aggregate invoices/tasks in batches, without full notes.
