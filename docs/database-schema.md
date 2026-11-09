# Database schema — Prompt 2

Schema foundations and migration checks began in Prompt 2. Prompt 4 adds migration `0002`, storing `booking_notes.request_fingerprint` (SHA-256) and `save_result` (JSON) so retries return the original note/snapshot after later updates. Prompt 7B adds migration `0003`, storing `booking_tasks.request_fingerprint` and `create_result` for durable task-creation replay. Apply `alembic upgrade head` before running the booking/task API. The initial migration remains frozen. Prompt 8C adds migration `0004`: nullable unsigned SMALLINT reminder days and the twelfth application table, `integrity_runs`. See [safeguards-integrity.md](safeguards-integrity.md) before upgrading existing status defaults.

## Files and storage rules

- `backend/app/models/base.py`: declarative base, table options, UTC timestamp type/mixins.
- `backend/app/models/entities.py`: `Mapped[...]` models for the ten requested tables plus invoice storage required by Prompts 1/1B.
- `backend/alembic/versions/0001_create_booking_tracker_schema.py`: frozen migration with explicit columns/indexes; it does not import live model metadata.
- `backend/app/scripts/seed.py`: repeatable status/admin seed command.
- `backend/tests/run_schema_checks.py`: disposable Docker database runner with verified TLS.

Tables use InnoDB, `utf8mb4`, and `utf8mb4_unicode_ci`. Booking identity columns on both sides of joins use ASCII with `ascii_bin`. IDs and logical numeric references use `BIGINT UNSIGNED`. There are no database foreign keys: services must validate references and related writes atomically. Future services must use explicit joins/preloads rather than implicit lazy loading.

`UTCDateTime` stores UTC `DATETIME(3)`, rejects naive Python datetimes, truncates to milliseconds, and returns aware UTC values. Sessions use UTC. Creation timestamps use `CURRENT_TIMESTAMP(3)`; mutable records have automatic update timestamps. Notes have no `updated_at` because they are append-only. No triggers or stored procedures are used.

### Additions retained from Prompt 1B

The abbreviated Prompt 2 list predates fields already required by the shared contract. This schema retains `statuses.default_task_days` / `invoice_required`, all six notification types, `bookings.invoice_state` / `invoice_count`, `booking_invoices`, and `booking_notes.invoice_change` JSON. These are storage prerequisites, not invoice APIs or business validation. Watch/assignment/push feature tables are deferred to their prompts.

## Migrate, seed, rollback

From `backend`, configure `.env` or securely injected process variables:

| Variable | Meaning |
| --- | --- |
| `DATABASE_URL` | `mysql+aiomysql` URL with database, URL-encoded credentials, optional `?charset=utf8mb4` |
| `DB_POOL_SIZE` | Default 5; total connections including overflow cannot exceed 10 |
| `DB_SSL` | Default true; verified TLS required in production |
| `DATABASE_SSL` | Existing compatible alias; both flags must agree if supplied |
| `DATABASE_SSL_CA` | Optional trusted public CA bundle; system trust otherwise |
| `ADMIN_USERNAME` | Required for full seed; at most 50 characters |
| `ADMIN_PASSWORD` | Required for full seed; at least 12 characters; never committed |

```sh
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/alembic check
.venv/bin/python -m app.scripts.seed
```

The full seed validates credentials before changing anything. There is no default password. Argon2id hashes are stored; plaintext credentials are never printed. Existing active Admins retain their password. A matching agent/QC or inactive account causes failure instead of privilege escalation/reactivation. Existing status values, including Admin edits, are preserved. Run seeds serially.

When admin credentials are unavailable, explicitly seed statuses only:

```sh
.venv/bin/python -m app.scripts.seed --statuses-only
```

Rollback/re-migrate on a disposable database or after an appropriate backup:

```sh
.venv/bin/alembic downgrade base
.venv/bin/alembic upgrade head
```

Downgrade deletes all application tables and data; Alembic's empty version table remains. MySQL/TiDB DDL is not one transactional application-data rollback. Do not downgrade valuable data as a routine restart step.

## Provisional status seeds

Position labels remain provisional because Prompt 1 §4.2 did not supply the mapping. Prompt 4 explicitly requires notes for Rejection/Parking; newly seeded rows now enforce that rule. Existing rows and operator edits are preserved: on a previously seeded database, an operator must enable `note_required` for these two statuses if they still have the former false defaults.

| Code | Label / Position | Note required | Done | Suggest task | Invoice required | Order |
| --- | --- | --- | --- | --- | --- | --- |
| `DONE` | Done | false | true | false | true | 10 |
| `REJECTION` | Rejection | true | false | true | false | 20 |
| `PARKING` | Parking | true | false | true | false | 30 |
| `BUNDLE` | Bundle | false | false | false | false | 40 |
| `HRS_PREVIEW` | HRS Preview | false | false | false | false | 50 |

All are active; `stale_after_hours` and `default_task_days` remain NULL instead of inventing per-status thresholds/reminder periods. Admin timezone defaults to `BUSINESS_TIMEZONE`. Supplier normalization removes accents/punctuation, lowercases, and collapses spaces without changing the original supplier name.

## Canonical storage validation

MySQL 8.0.16+ gets `CHECK (booking_key = UPPER(booking_key) AND booking_key NOT LIKE '% %')`. On TiDB the migration inspects `tidb_enable_check_constraint`; it adds the CHECK only when enforcement is enabled and never changes a production-wide variable automatically. The v8.5.0 test image defaults to OFF.

When CHECK enforcement is unavailable, migration logs the fallback. `require_canonical_storage_key` and the ORM validator reject non-uppercase/non-ASCII/whitespace keys. Future service writes, including Core/bulk inserts, must call this guard explicitly; raw SQL bypasses application validation. Prompt 4 additionally validates full-key syntax, months, station ownership, and canonical path spelling before every new note write.

To use CHECK on TiDB, have the cluster administrator enable it before the initial migration. Enabling it afterward does not create an omitted constraint; adding it later requires a reviewed migration and existing-data validation. The disposable TiDB test covers both OFF fallback and ON re-migration.

## Index rationale

Requested index prefixes are preserved. Ordered-list indexes explicitly append `id` to support deterministic `ORDER BY ..., id DESC`. MySQL can use an implicit PK suffix; TiDB v8.5.0 testing showed an explicit key part was necessary to avoid sorting/full scans. These extend existing indexes rather than adding duplicate parallel indexes. There is exactly one UNIQUE `booking_key` index and no separate hash/plain duplicate.

| Table | Index columns | Purpose |
| --- | --- | --- |
| users | UNIQUE `username` | Login lookup and uniqueness |
| statuses | UNIQUE `code` | Dynamic status lookup |
| stations | PK `code` | Station lookup/join |
| bookings | UNIQUE `booking_key` | Exact point lookup |
| bookings | `last_agent_id, updated_at, id` | My bookings, newest first |
| bookings | `updated_at, id` | Overall newest-first list |
| bookings | `last_status_id, updated_at, id` | Status-filtered lists |
| bookings | `is_done, updated_at, id` | Open/done lists |
| bookings | `group_id, period, id` | Folder months |
| bookings | `station_code, period, id` | Station/month list |
| bookings | `cw_number, period` (not UNIQUE) | Partial lookup; legacy ambiguity remains possible |
| bookings | `last_note_id` | Logical latest-note reference |
| booking_groups | UNIQUE `cw_number` | One folder per CW |
| booking_groups | `station_code, supplier_type, last_activity_at, id` | Station/type folders by activity |
| booking_groups | `supplier_name_normalized` | Prefix/equality supplier search; leading-wildcard search is not guaranteed to use it |
| booking_groups | `last_activity_at` | Activity access |
| booking_groups | `created_by` | Logical creator reference |
| booking_notes | `booking_id, created_at, id` | Cursor history for one booking |
| booking_notes | `created_at` | Time-range/daily reports |
| booking_notes | `agent_id, created_at` | Agent activity |
| booking_notes | `deleted_at` | Trash filtering |
| booking_notes | `status_id`, `deleted_by` separately | Logical references |
| booking_notes | UNIQUE `client_request_id` | Retry deduplication; multiple NULLs allowed |
| attachments | `note_id` | Attachments of a selected note |
| notifications | `user_id, read_at, created_at` | Own/unread notifications |
| notifications | `user_id, created_at, id` | Per-user notification feed order |
| notifications | `booking_id`, `task_id`, `note_id`, `by_agent_id` separately | Indexed logical references |
| audit_logs | `created_at` | Chronological audit |
| audit_logs | `user_id, created_at` | Per-user audit |
| audit_logs | `entity_type, entity_id` | Per-entity audit |
| booking_tasks | `user_id, status, remind_at` | Own pending/due tasks |
| booking_tasks | `user_id, status, completed_at, id` | Per-user completed-task feed ordering |
| booking_tasks | `status, notified_at, remind_at` | Background due notifications |
| booking_tasks | `booking_id, user_id, status` | Own pending tasks for a booking |
| booking_tasks | `note_id` | Logical source-note reference |
| booking_tasks | UNIQUE `client_request_id` | Task retry deduplication |
| booking_invoices | UNIQUE `booking_id, invoice_number` | Per-booking uniqueness/list lookup |
| booking_invoices | `invoice_number` | Cross-booking invoice lookup |
| booking_invoices | `added_by` | Creator reference/ownership lookup |

Each numeric table also has its BIGINT primary key. Leading composite columns cover logical reference indexing where possible, avoiding redundant single-column indexes.

## Reproducible EXPLAIN evidence

The fixture contains **2,000 folders, 24,000 bookings, 48,000 notes**. Queries use no FORCE INDEX or optimizer hints. From `backend` with Docker available:

TiDB's [ANALYZE compatibility note](https://docs.pingcap.com/tidb/stable/sql-statement-analyze-table/#mysql-compatibility) documents a short delay after recent commits. The fixture waits one second before `ANALYZE ... ALL COLUMNS`, then verifies the observed statistics row count before checking plans; it does not assume a completed bulk insert means the statistics are current.

```sh
.venv/bin/python tests/run_schema_checks.py --engine mysql --report /tmp/explain-mysql.json
.venv/bin/python tests/run_schema_checks.py --engine tidb --report /tmp/explain-tidb.json
```

The runner generates a temporary test CA/server certificate, verifies TLS trust and hostname, binds only to loopback, and removes its own container/certificates afterward. It generates a fresh database URL instead of using your configured application database. No reusable external credentials are involved.

Reports from the current successful runs: [MySQL](schema/explain-mysql.json), [TiDB](schema/explain-tidb.json). Query text is in `backend/tests/test_schema_database.py`. Reports are written only after migration, seed/CLI repeatability, plan checks, rollback, re-migration, and metadata parity pass.

The eight queries are (a) my bookings by updated time, (b) undeleted note history, (c) overall newest-first list, (d) station/type folders by activity, (e) folder months, (f) station/period bookings ordered by ID, (g) exact key, (h) CW/period. Ordered lists use `id DESC` as a tie breaker. MySQL must show `const` on `booking_key`, `ref` for CW/period, and no `Using filesort`/`Using temporary`. An additional folder JOIN must show `eq_ref`.

TiDB exact lookup must be `Point_Get`; lists/partial lookup use their intended secondary indexes. All eight queries reject full table scans and `Sort`/`TopN`. The additional JOIN may use `IndexJoin`/`IndexHashJoin` and bounded TopN to restore order: this is a documented TiDB join exception, not a sort-free claim. MySQL rejects filesort/temporary for all nine queries.

These plan checks are not latency measurements or a guarantee for every future filter/sort combination. Recheck on the actual TiDB Cloud version/region with representative data. CI repeats both engines and uploads fresh reports.


Prompt 8D advances head to **0005**, adding booking_watchers and booking_assignments
(14 application tables total), notification merged_count and nullable generated unique
guards. Earlier migrations are unchanged; model/migration parity and downgrade/upgrade
are checked on both engines. See [collaboration.md](collaboration.md).


Prompt8E advances head to **0006** and 16 application tables: daily_reports stores
final/provisional JSON snapshots (including internal frozen export source), while
push_subscriptions uses an ASCII-unique endpoint plus user/current-session binding.
The optional MySQL ngram FULLTEXT index is separate DDL and explicitly excluded from
mandatory Alembic drift removal; it is not installed on TiDB. See operations-pwa.md.


Prompt 8F head **0007** retains 16 tables. It adds ASCII binary
booking_invoices.invoice_number_normalized, unique (booking_id, normalized),
normalized-number/created-time indexes and bookings (period, invoice_state) /
(invoice_state, is_done, updated_at) indexes; invoice_count becomes unsigned SMALLINT.
Earlier invoice/status/note columns already exist and are preserved. Upgrade,
rollback and the four EXPLAIN cases are documented in [invoices.md](invoices.md).


Prompt 9 head **0008** is additive: `users.must_change_password` is NOT NULL with
server default false; upgrade marks rows with last_login_at IS NULL for first-login
rotation. New/seed/reset application writes explicitly set true. Seed reruns preserve
an existing user's completed rotation. Existing migrations remain unchanged.
Downgrade removes only this enforcement flag, so it must be coordinated with the
older application version; it does not recover temporary-password history.

## Prompt 10: migration 0009

Additive indexes: notifications `(read_at,id)`, terminal-task retention
`(status,updated_at,id)`, and live-note daily-report aggregation
`(deleted_at,booking_id,id,created_at)`. Existing migrations 0001–0008 remain
unchanged. Upgrade with `alembic upgrade head`; downgrade drops only these indexes.
Retention runs in the scheduler, independently of migration, using configured ages.

## Migration 0011: user feed indexes

Migration `0011_user_feed_indexes` adds two user-scoped composite indexes after
reviewing the actual SQL shapes: notifications are selected by `user_id` and ordered
by `(created_at DESC, id DESC)` without a `read_at` filter; completed tasks are
selected by `(user_id, status='done')` and ordered by `(completed_at DESC, id DESC)`.
The existing unread-count index has `read_at` between `user_id` and `created_at`, so
it cannot provide the all-notifications feed order when read and unread rows are
mixed. The existing task reminder index ends in `remind_at`, not `completed_at`.

The migration adds ordinary composite B-tree indexes, portable across the supported
MySQL/TiDB engines. They consume storage and add write maintenance; the schema plan
suite now populates 15,000 notifications and 15,000 completed tasks and checks that
these list shapes use the intended indexes without sort operators on both engines.
Run `alembic upgrade head` once as a release step; never edit migrations 0001–0010.
Plan selection on synthetic fixtures is not a production latency guarantee. Compare
provider-side rows examined/latency and write rate after rollout before concluding
the indexes improved production performance.

## Migration 0012: supplier classification and station folders

A folder is unique on `(cw_number, station_code)`. The old CW-only unique index
is replaced without changing existing IDs or booking references. Supplier type
adds `unclassified` as an explicit default; existing hotel/transportation values
are preserved. Bookings may still have no notes/status. Special CW identifiers
with 4–10 uppercase alphanumeric characters (including at least one letter) are
accepted in addition to the existing 5–10 digit identifiers.

Admin import is preview-first and insert-only, accepts up to 1000 CSV/TSV source
rows, expands explicit multi-station partial keys, and refuses conflicting
duplicates atomically. It preserves existing metadata and snapshots. Supplier
classification is retained across periods for the same CW/station. Downgrade
refuses to remove unclassified values or multi-station folders; operators must
resolve representability before returning to the previous schema.
