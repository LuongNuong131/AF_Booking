# Measured load results — 04 Nov 2026

Functional regression, migrations, security gates and service coverage pass.
**The mixed-load and key latency goals are not yet met consistently.** The manual
load job therefore fails its original threshold assertions; these failures have
not been disabled, relabeled as passes or added to an exclusion list.

The final application source was measured on both engines with default pool size
5, one API worker, verified loopback TLS through a forwarding proxy, 50 acting
users and 100 real WS peers. The shared workspace has 4 CPU quota units and 32 GiB
memory; the SQL container, API and load generator share it. TiDB is local v8.5
unistore, not TiDB Cloud. Each measured phase lasts 60 s with a 10 s warmup.

| Run | REST p50 ms | REST p95 ms | Worst key server p95 ms | Broadcast p95 ms | Unexpected HTTP errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| MySQL current defaults | 32.81 | 328.29 | 54.59 | 224.68 | 0 |
| TiDB current defaults | 51.52 | 465.07 | 97.03 | 216.84 | 0 |
| Goal | <100 | <300 | <50 | <500 | 0 |

All four key groups are counted: canonical full, formatted, partial and absent.
REST latency includes response receipt; Server-Timing measures server work to
headers. Actual per-group samples, p99, request counts, query plans and cache
counters are retained in the raw reports. Daily report cold generation remains
seconds rather than milliseconds at this dataset size; it is included if it
occurs after the warmup. No report rows are truncated to improve these numbers.

## Before and after

| Measurement | Before REST p95 ms | After REST p95 ms | Scope |
| --- | ---: | ---: | --- |
| MySQL | 2314.47 | 328.29 | Initial mixed baseline to current application; initial run had two timeouts |
| TiDB | 1360.91 | 465.07 | Analyzed dataset, before/after bounded note-search detail IDs |

These baselines represent different optimization stages, so compare each engine
with its own baseline. The initial MySQL failure stopped before key/fault phases;
no before-key or before-broadcast percentile is invented. Earlier development
trials varied with query shape and shared CPU scheduling; one earlier MySQL trial
met the targets, but the current-source run above did not. It is not a stable
capacity guarantee. A separate GOMAXPROCS=2 TiDB experiment worsened latency
(REST p95 535.37 ms; key p95 176.82 ms), so that test-container setting was reverted.

Daily-report invoice aggregation now batches instead of correlated per-booking
queries. Streamed reads, cooperative complete JSON/gzip encoding and cached wire
bytes reduce event-loop stalls. Migration 0009 adds a covering live-note index.
The actual TiDB note-search plan initially read 250,000 historical note rows even
with a nested LIMIT. Selecting page IDs in a separate bounded query changes the
detail read to a Batch/Range point path. Search retains its date window and all
ownership/deletion rules. Lookup uses one transaction with combined private
reads and cold invoice/snapshot data; history limits notes before attachment joins.

EXPLAIN confirms MySQL `type=const` and TiDB `Point_Get` for unique booking-key
lookup. My bookings uses the agent/activity index; note text filtering uses the
date index. `latest_before` ignores the new live-note covering index for diagnostic
comparison; `latest_after` can use it. This plan comparison is not another
pre-change timing run.

Both final runs delivered the probe to all **100/100 peers**, had **zero unexpected
HTTP errors**, and returned **12 sanitized REQUEST_TIMEOUT/504 responses** during
real two-second-per-direction DB delay injection. After removing delay, health
and an uncached lookup recovered. Pool-exhaustion/Retry-After and connection-discard
checks also pass in the separate business suites.

The remaining performance work is to isolate cold-report CPU and profile
connection/SQL scheduling under the actual Render/TiDB Cloud resources, then
repeat this same 50-user test on isolated infrastructure. The current evidence
does not justify a production p95 promise. Hosting and remote network latency
have not been measured.

## Raw evidence

- [Initial partial MySQL baseline](load-before.json)
- [Current MySQL](load-after-mysql.json)
- [TiDB before final search fix](load-before-tidb.json)
- [Current TiDB](load-after-tidb.json)
- [Reverted TiDB scheduling experiment](load-experiment-tidb-gomax2.json)
- [Note search plan before](note-search-plans-before.json) / [after](note-search-plans-after.json)
- [Reproduction and strict gates](load-testing.md)

The legacy `label: baseline` field in the current-default raw runs predates
report labeling; filenames, commands and this comparison identify their scope.
New harness runs use `prompt10-current` and include the DB version explicitly.
Synthetic EXPLAIN literals are test inputs; production telemetry retains only
fingerprints, never SQL text or parameters.
