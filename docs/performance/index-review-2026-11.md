# SQL and index review — 9 Nov 2026

## Scope and evidence

Reviewed the ORM queries under `backend/app/services/`, model/index definitions in `backend/app/models/entities.py`, Alembic migrations through `0010`, existing MySQL/TiDB EXPLAIN fixtures and available performance reports. The repository contains useful synthetic plan/performance evidence, but no production slow-query log, production `EXPLAIN ANALYZE`, production table cardinalities, or production read/write mix was available for this review. Therefore this report distinguishes plan-shaped risk from proven production latency.

The index additions are in migration `0011_user_feed_indexes`. The schema suite now fills 15,000 rows in each of `notifications` and `booking_tasks` and asserts both query shapes use their intended key without MySQL filesort or TiDB sort/TopN. This fixture is representative of the optimizer's non-tiny-table choice, not a claim of production performance. The current sandbox lacked Docker, so disposable MySQL/TiDB migration and EXPLAIN suites could not be run locally; CI must pass those gates before rollout.

## Applied changes

| Priority | Query shape | Existing gap | Change |
| --- | --- | --- | --- |
| High, bounded feed | `notifications WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT ?` (`app/api/v1/notifications.py`) | Existing `user_id,read_at,created_at` index has unconstrained `read_at` between the user equality and sort keys; it also serves unread count/read-all and should remain. | Add `ix_notifications_user_created_id(user_id,created_at,id)` for chronological per-user feed access. |
| Medium, user task history | `booking_tasks WHERE user_id=? AND status='done' ORDER BY completed_at DESC,id DESC LIMIT ?` (`services/tasks.py`) | Existing `(user_id,status,remind_at)` covers pending/due work but not completed-time ordering. Completed tasks are retained for a bounded period. | Add `ix_booking_tasks_user_status_completed(user_id,status,completed_at,id)`. |

Both are ordinary composite B-tree indexes, and their column order directly mirrors equality filters followed by deterministic ordering. They carry storage and write-maintenance cost; the migration does not remove existing indexes because their other query paths differ.

## Slow-query risks reviewed but not given speculative indexes

| Query shape | Potential issue | Decision / next verification |
| --- | --- | --- |
| Integrity `batch_query` over latest notes by booking, repeated for each 1,000-booking batch | Saved 50k fixture plans show MySQL reading a broad live-note index range before the batch join; TiDB includes broad scans around derived/hash-join paths. Recorded 50k integrity runtime is 6.42 s MySQL / 13.729 s TiDB and lookup p95 during scan 44.188 / 46.671 ms. Existing `(deleted_at,booking_id,id,created_at)` and invoice `(booking_id,normalized)` indexes cover the logical access keys. | Do not add another near-duplicate index: the suspected cost is plan shape/repeated work. Test a batch-constrained aggregate/rewrite first; compare rows scanned per batch and lookup p95 on both engines. See `docs/performance/integrity-prompt10-{mysql,tidb}.json` and `backend/tests/test_integrity_performance.py`. |
| Performance report done-booking aggregate filtered on `is_done=true AND done_at in range`, grouped by `last_agent_id` | Existing `(is_done,updated_at,id)` does not seek `done_at`. | Conditional candidate `(is_done,done_at,last_agent_id)` only if production EXPLAIN shows a broad scan and date range is selective. No index added without actual plans; see `backend/app/services/reports.py`. |
| Invoice export `bookings WHERE period=? ORDER BY id`, joined to invoices ordered by invoice ID | `(period,invoice_state)` helps period filtering but does not encode requested booking-ID order. | Conditional `(period,id)` only if both-engine plan shows expensive sort/rows examined on representative period sizes. Exports are streamed and no production evidence exists. |
| Assignments with omitted `status`, filtered by recipient/sender and ordered by `created_at,id` | Existing indexes put status between user ID and creation timestamp, so the no-status shape may sort. Route default is `open`; normal filtered path is already covered. | Conditional direction-specific `(to_user_id,created_at,id)` or `(from_user_id,created_at,id)` only if no-status usage and plan cost are material. Do not add both from source inspection alone. |
| Folder card latest booking derived query | Existing `group_id,period,id` range is used, while saved TiDB plan materializes/scans a derived latest relation. | Likely a query rewrite/optimizer issue, not a missing index. Preserve tie-breaking and folder aggregates; verify actual rows/loops on 20, 100 and larger group-ID sets before changing. |
| Per-booking invoice list sort by invoice ID | Existing unique `(booking_id,invoice_number_normalized)` locates invoices, but saved tiny fixture may sort. | Invoice count is capped at 20 per booking; added `(booking_id,id)` is not justified absent measured end-to-end cost. |
| Note text search `LIKE '%term%'` | Leading-wildcard text search is non-sargable; range/date index bounds candidates and the query is limited by date window. | Do not add a normal B-tree for text. Optional MySQL ngram fulltext is already a separate, non-TiDB feature with different semantics. |
| Numbered-page APIs using `OFFSET` | Deep offsets can still scan/skip rows even with correct ordering indexes. | Prefer a keyset/API/UI contract migration if deep pages are observed. Adding an index does not remove offset cost; see `docs/database-operations.md`. |

## Operational validation

Before deploying the migration, run the dual-engine schema suite against disposable databases and check the new plan artifacts. After deployment, compare provider-side active connections, rows examined, query latency, write rates and storage; include both the notification feed and completed-task list in a representative workload. If the two indexes do not materially reduce sort/scan cost, reconsider them against their ongoing write/storage cost.

The existing load report records that the shared-runner mixed-load REST/key p95 goals were not consistently met and that Render/TiDB Cloud latency was not measured. These additions do not claim to solve those broader latency gaps or establish a production SLA.
