# Booking safeguards and snapshot integrity (Prompt 8C)

## Upgrade

Run `backend/.venv/bin/alembic upgrade head` from the intended backend environment
(or `.venv/bin/alembic upgrade head` while in `backend`). New head is **0004**.
Migrations 0001–0003 are unchanged. The task-day field was already provisioned as
unsigned INTEGER in 0001; 0004 changes it to nullable unsigned SMALLINT and creates
`integrity_runs`. It rejects out-of-range old values before narrowing the column.
Existing non-null values are preserved. Existing null values for REJECTION/PARKING
receive the requested assumed defaults 3/2; Admin can clear them after upgrade to
disable the status-specific suggestion. New seed rows also use 3/2. Repeat seeding
never overwrites Admin changes. Downgrade widens the column and drops run history;
it does not undo subsequent task-day edits or reconstruct old null choices.

## Near-key suggestions

After normalizing a full key, the server enumerates numeric CW substitutions,
insertions, deletions and adjacent swaps, plus the same CW's ±1/±2 calendar months.
Edits never combine a different CW with a different month. Candidate CWs stay 5–10
digits; month bounds stay 2000–2099 without century wrap. A numeric edit/swap has
distance 1; a month candidate has distance equal to its month offset. The candidate
set is deduplicated and capped below 250.

When KeyIndex is ready, each candidate uses an O(1) key probe, with its folder's
station where known. No match means no suggestion query. Matches are hydrated with
one bounded metadata query and ranked by distance, newest booking updated_at and key
as a stable tie breaker; return at most three. If the index is unready/disabled,
a single statement builds a small derived candidate set, resolves stations through
the unique CW index and uses `booking_key IN (candidate keys)` against the unique
booking-key index. Explicit ASCII collation matches stored keys in both MySQL/TiDB.
There is no booking-table scan in application code and no Supplier LIKE path.

A partial new CW never guesses a station or returns cross-station suggestions;
Station code must be entered first. A partial known CW resolves its station and then
can offer month suggestions. Suggested values include canonical/display keys,
status, final agent, updated_at and distance.

Missing-booking UI displays a yellow warning with keyboard/click choices. Save
requires the explicit **This is a new booking** button, even when there are no
suggestions. Arrow keys act on search choices without stealing textarea editing
keys. The server independently requires `confirm_new:true` when a missing booking
has suggestions (`NEW_BOOKING_NEEDS_CONFIRM`, details.suggestions); creation remains
atomic and failure leaves no folder/station/booking behind.

## Duplicate notes and outbox

After UUID replay and version checks, the server reads the current user's live notes
for this booking/status in the last 60 seconds, using the booking/creation index.
Comparison trims/collapses whitespace and casefolds text; null/blank is the same
normalized empty text. Other users/statuses/bookings and soft-deleted/out-of-window
notes are excluded. Identical UUID replay returns the original result before this
check, including after moderation or later notes.

A match returns `DUPLICATE_RECENT_NOTE`/409 with details.note (the public Note DTO,
not its replay blob/fingerprint) and details.seconds. The dialog offers Cancel or
Send anyway. Cancel retains the restored form. Send anyway creates a new operation
with `allow_duplicate:true` and a new UUID; ordinary temporary retries keep their
original UUID/payload. Both safeguard errors are business failures: outbox removes
the optimistic operation, restores an empty active form or keeps a blocked entry for
review, and never automatically retries it. Drafts being edited are preserved.

After a committed save, a status-specific reminder shows its actual local date/time
and opens TaskDialog with the corresponding day chip selected, honoring the existing
profile timezone/weekend/default-time rules. Null days disable the automatic suggestion bar; the manual Task button remains available. It does not create a task automatically.

## Integrity checks and repair

Only Admin can list/start/fix runs at `/admin/integrity`. GET returns a paginated
history plus `autofix_enabled,run_time,timezone`; automatic repair is visible in the UI.
POST run/fix acknowledge a persisted run with 202 and continue in application-owned
work. One run is active per backend; another start returns SERVICE_BUSY/503. Run
states are running/completed/failed/interrupted. Errors remain sanitized. At startup
or the first history/start access, runs left running by the old process become
interrupted; a new check starts from the beginning rather than trusting an old cursor.

The scan fixes its starting high-water booking ID, takes 1,000-booking keyset batches,
and sleeps 50 ms between batches. Each batch selects the latest **non-deleted MAX(id)**
note for its own bounded set, not a fresh whole-table aggregate. It compares last note,
agent, status, stored position, Done flag/time and additionally last_note_preview for
complete snapshot consistency. Only 255 characters of source note text cross the DB
connection in the scan. With no live note these snapshot fields clear. Done time is
the source note's original creation time; timestamps do not decide the latest ID.
Admin soft delete/restore now uses this same derivation/MAX-ID ordering.

Every run counts the entire scan but stores at most 200 detailed findings. `truncated`
marks a larger result. Details include canonical/display keys, field-level stored vs
expected values, repairability and sampled repair outcomes. A missing source status
is reported as unrepairable and skipped, rather than inventing a Done state. Repair
uses live source data, not JSON values from a previous report.

`POST /fix {run_id}` requires a finished run with mismatches. It starts a **new full
scan** and repairs all current mismatches, including those beyond the 200-item sample;
the UI confirmation states this scope. Each repair locks/rechecks the Admin (for a
manual run), then group and booking, rereads the latest live note and changes only
an actual mismatch. It increments version, invalidates snapshot/report caches,
refreshes KeyIndex, writes an audit row and broadcasts booking.updated with
snapshot_rebuilt:true after commit. The fixed counter increments in that same
transaction, surviving a lost HTTP response/cancellation. Repeating repair of an
already-correct booking creates no new version/audit/event. Invoices, folder activity
and operational updated_at are preserved; integrity repair does not make an old
booking appear recently worked. A stale notification marker is reset on correction.

Nightly scheduling defaults to **02:00 in BUSINESS_TIMEZONE**. Set
`INTEGRITY_RUN_TIME=HH:MM` and `INTEGRITY_AUTOFIX=true` only when automatic repair is
intended. Default is report only. Scheduler checks eligibility every 30 seconds,
catches up after a sleeping instance wakes, and records the business date so a restart
cannot repeat that night's completed/failed attempt. A skipped spring-forward 02:00
runs when the service next observes local time after it. `INTEGRITY_TIMEOUT_SECONDS`
defaults to 600; interrupted/failed jobs remain reviewable. Other scheduler jobs and
HTTP requests continue independently. Admin progress reads every two seconds only
while its page has an active run; a read error/disposal stops those reads. Task lists
still have no polling. One backend instance/worker remains required.

## Verification and measurements

On each disposable, verified-TLS MySQL 8.0.46 and TiDB 8.5.0, safeguard tests cover all
edit types, month boundaries/stations, unknown partial CWs, confirmation, one-statement
fallback/ranking, duplicate normalization/expiry/UUID override, incorrect and empty
snapshots, MAX-ID semantics, audit/realtime, ACL, single-run exclusion, restart,
cancellation, scheduled catch-up/autofix and upgrading old task-day values.

The benchmark seeds 2,000 folders, 50,000 bookings and 50,000 real notes, with 250
intentional mismatches. It checks the 200-item detail bound, detects every mismatch,
then repairs all 250 beyond that sample, while measuring concurrent authenticated
lookup. Raw EXPLAIN/metrics are in `performance/integrity-{mysql,tidb}.json`.

| Local measurement | MySQL | TiDB |
| --- | ---: | ---: |
| Check 50,000 | 10.500 s | 8.933 s |
| Rescan + repair 250 | 14.963 s | 15.065 s |
| Baseline lookup p95 | 15.152 ms | 18.402 ms |
| Lookup p95 during check | 55.055 ms | 39.859 ms |

The scan adds about 22–40 ms at p95 in this workload, staying below the 100 ms local
API budget and far below the 180-second scan limit. These are loopback ASGI/TLS tests,
not hosted network/cold-start measurements or a production SLA.

From repository root:

```sh
backend/.venv/bin/python backend/tests/run_schema_checks.py --engine mysql --suite safeguards --report /tmp/safeguards-mysql.xml
backend/.venv/bin/python backend/tests/run_schema_checks.py --engine tidb --suite integrity-performance --report /tmp/integrity-tidb.json
BOOKING_CHROMIUM_PATH=/usr/bin/chromium backend/.venv/bin/python backend/tests/run_schema_checks.py --engine tidb --suite frontend --report /tmp/browser.xml
```

The new browser scenario exercises keyboard suggestion selection, explicit creation,
duplicate Cancel/Send anyway, preset reminder days and Admin check/repair/mobile/ACL
against a real server. A test-harness-only command corrupts its disposable booking;
there is no production corruption endpoint.


The same 50k fixture also verifies the index-unready suggestion fallback with a new
CW and a different input station: it resolves the candidate's actual RDU folder.
MySQL EXPLAIN uses `eq_ref` on `booking_key`; TiDB uses an IndexRangeScan on that unique
key. The entire derived-candidate fallback is one statement, measured at 68.958 ms /
63.945 ms respectively, below its 3-second budget. The raw reports retain both plans.
