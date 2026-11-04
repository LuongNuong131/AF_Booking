# Invoice management and monthly reconciliation — Prompt 8F

## Upgrade

From `backend`, run `.venv/bin/alembic upgrade head`, then `.venv/bin/alembic check`.
Head **0007** adds the normalized invoice column/unique and lookup/created-time
indexes, the two booking reconciliation indexes, and narrows invoice_count to
unsigned SMALLINT. No dependency or secret changes are needed. Migrations 0001–0006
remain unchanged. Roll back only an owned disposable/development database with
`.venv/bin/alembic downgrade 0006`; normalized lookup support is then removed.

The initial schema already contained invoice state/count, invoice rows,
status.invoice_required and note.invoice_change, and earlier prompts already used
inline declarations. **Existing explicit declarations/rows are preserved**; unset
legacy bookings remain unknown. The migration does not guess invoices, mark old Done
bookings no-invoice, reset valid declarations, or override Admin-edited status rules.
DONE's default invoice_required=true comes from the repeatable status seed; Admin
can change it. This adapts the requested additive migration to the actual existing
schema without recreating columns or erasing user data.

`INVOICE_NUMBER_PATTERN` defaults to `^[A-Z0-9][A-Z0-9\-_/.]{2,39}$` and
`INVOICE_MAX_PER_BOOKING` to 20. Storage remains at most 40 ASCII characters;
configure a compatible pattern. Input is trimmed, uppercased and stripped of
control/format characters. Shared Python/TypeScript fixtures in
`fixtures/invoice-input.json` cover comma/semicolon/whitespace parsing and ordered
deduplication. A request accepts at most 50 add values and 50 removal IDs.

## Atomic behavior and ownership

`InvoiceService.apply_changes` is used by both note creation and standalone PUT.
The caller holds fresh actor/session, group and booking locks in the existing lock
order. The transaction validates all inputs and removal rights before changing rows:

1. Remove matching IDs from this booking; missing/other-booking IDs are ignored.
2. Add normalized numbers; existing numbers are returned in skipped_duplicates.
3. Reject no_invoice=true with remaining rows. Otherwise remaining rows mean
   has_invoice, an empty explicit no_invoice=true means no_invoice, and an empty
   changed set with no true declaration means unknown.

A note without an invoices field preserves the existing declaration. After optional
changes, invoice_required rejects an unknown declaration with INVOICE_REQUIRED and
rolls back the whole note transaction. Standalone PUT can clear a Done booking's
declaration without creating a note or retroactively blocking the booking.

Only the adding user or QC/Admin can delete an existing row. Any forbidden removal,
invalid number, state conflict or limit violation rolls back the whole request.
Audit actions are invoice.add, invoice.remove, invoice.no_invoice_set and
invoice.no_invoice_clear, at most one row/type/request; metadata includes affected
numbers and adding users. A no-op retry adds no duplicate row/audit change.

New numbers use **one indexed IN query** to warn about use on other bookings, up to
five canonical keys per number. Warnings never block saving. New inline note results
retain those warnings/skips and complete Invoice objects with real IDs, so owners
can edit newly committed chips immediately. Pre-8F persisted UUID responses use a
null full-invoice extension rather than fabricate historical IDs; the client retains
its current list until lookup. Note.invoice_change records only that
note's added/removed/declaration effects. Note delete/restore never changes invoices.

PUT needs **no expected_version**: row-locked set operations allow two users to add
different numbers without losing either update. Every successful PUT increments
version, invalidates snapshots/list generations and the invoice report cache, then
broadcasts booking.updated/change_kind=invoice. It does not create a note,
notification, takeover, group activity, advisory unlock or task, and does not change
last agent/status/position/Done or the stale clock. The UPDATE explicitly binds the
unchanged updated_at value, including after an uncertain retry.

## Reads, search and realtime

GET `/bookings/{key}/invoices` returns state, all Invoice objects, number_pattern and
max_per_booking. Lookup/detail include all invoices plus invoice_rules for the
client validator. Lists use the existing single batch/window query for up to three
newest invoice previews; folder months carry state/count. No per-row query is added.

`INV:number` and `#number` explicitly select an exact normalized invoice lookup.
Supplier TEXT searches keep their ranking first; only an empty supplier result and
a valid invoice value trigger one indexed invoice fallback. If that fallback is
empty, kind remains none; an explicit invoice search may return kind=invoice with
an empty page. Matching rows add matched_invoice. Key-shaped searches still never
enter Supplier LIKE. Summary supports exact invoice and invoice_state filters in
the URL, including is_done=true&invoice_state=unknown for QC completion work.

booking.updated adds invoice_state, invoice_count and change_kind (note/invoice).
The existing 100 ms version coalescer retains the newest event. Invoice-only events
refresh affected workspace/list data and patch open folder months without changing
folder activity/open/stale counts. Older clients may omit the added fields during
an upgrade; new server events always supply them. No invoice values/notification
content are put into the WebSocket event.

The 1,000-booking integrity scan includes one invoice aggregate constrained to each
batch. Repair rereads actual invoice rows under the booking lock, fixes count/state,
preserves no_invoice only when empty, increments version and publishes the repaired
snapshot. An invoice-only repair preserves the stale notification marker and clock.
It invalidates the reconciliation cache after commit.

## Reports and downloads

QC/Admin GET `/reports/invoices?period=YYMM` defaults to the current business period.
One aggregate query reads bookings only, using (period, invoice_state); there is no
invoice-table join. A bounded 45-second cache is invalidated by committed invoice
changes. Results include booking/state counts, sum(invoice_count), multi-invoice
count, average, maximum and zero/one/two/3+ distribution. The Reports invoice panel
has a month picker, metric cards, distribution bars, exports and an unknown-filter
link to Summary.

GET `/export/invoices?period=&format=xlsx|csv` is QC/Admin-only and audited. CSV is
the Invoices sheet. XLSX has Invoices and Bookings sheets. The first has one row per
invoice, plus one blank-number row for every booking with none; the second has one
row per booking, all numbers joined with `; `. State labels are Has invoice,
No invoice Number and Not declared. Both honor EXPORT_BOOKING_KEY_STYLE and apply
formula/control-character protection to every user-controlled cell. SQL streaming,
write-only XLSX, bounded spooling, the export deadline and disconnect cancellation
preserve the existing export behavior.

Daily record and newly generated daily-report Excel append Invoice State and
Invoice Numbers after Note. Daily JSON adds done_not_declared for bookings whose
final live note is Done that day and current declaration is unknown. Invoice data
is frozen with a report's other source rows; later invoice changes do not rewrite
a final report. Immutable pre-8F rows lacked this source data: their new Excel cells
show Not declared/blank rather than invent a historical invoice, and their missing
new list defaults empty. Existing aggregate/history data is never recomputed merely
for the schema extension.

## Interface and offline changes

InvoicePanel is shared by the note fields and read-only booking summary/detail.
Enter/paste commits ordered, uppercase chips; invalid chips show the supplied
English error and prevent Save. Existing chips copy their number and expose author
and time in a tooltip. Only authorized committed chips have a confirmed remove
action. Pending local chips can be removed before enqueue; queued temporary IDs are
not sent as deletions. No-invoice is disabled while chips remain; its tick locks
input. Alt+I focuses input and Alt+N toggles the empty declaration, through the
central shortcut registry/help. Duplicate-booking warnings link to display keys.
Tables show two preview numbers/+N, no-invoice grey, or unknown orange when Done;
month rows use their contracted count-only badge.

Drafts include input chips, removal IDs and the declaration. Notes retain their
exact UUID/payload through the existing per-user durable outbox. Standalone invoice
PUT uses the **same per-key ordered queue**, persists before clearing invoice fields
and leaves the note/status draft intact. Reopening the booking restores that draft.
Uncertain PUT replay keeps its exact set payload; an unattempted following note gets
the committed predecessor version. Invoice-only operations never insert a fake
Activity note or promote another agent's booking. INVOICE_* 4xx failures stop retries,
remove optimistic display and return the submitted changes for review; network/
429/5xx errors use the existing bounded backoff. One active editing tab/account
remains the outbox's existing limitation.

## Validation and manual check

Run the ordinary units/types/build plus `tests/run_schema_checks.py --engine mysql
--suite invoices --report /tmp/invoices-mysql.xml`, and repeat with tidb. Use only
the runner's disposable verified-TLS databases. The suite covers transaction rollback,
limits, ownership, concurrent writes/clock preservation, search, one-query preview/
report budgets, formula-safe XLSX/CSV, independent moderation and integrity repair.
Its EXPLAIN cases exercise booking invoice lists, exact normalized lookup,
period/state counts and undeclared Done queries. The browser runner includes
`invoices.mjs` for the real multi-user/offline/report flow.

Manually: save Done with two pasted numbers, confirm Activity changes, add a third
with Save invoices from a different agent, verify the original last agent/time are
unchanged, try removal as that agent versus QC, then check INV: search, monthly
counts and both Excel sheets. Block the API temporarily, enqueue invoice changes,
reload and reopen the booking, then reconnect: the queue should clear without
creating another note or losing an unfinished note draft.

Reproducible EXPLAIN statements (synthetic values; use an isolated database):

```sql
EXPLAIN SELECT * FROM booking_invoices WHERE booking_id=1 ORDER BY id;
EXPLAIN SELECT booking_id FROM booking_invoices
  WHERE invoice_number_normalized='INV501';
EXPLAIN SELECT invoice_state,COUNT(*) FROM bookings
  WHERE period='2609' GROUP BY invoice_state;
EXPLAIN SELECT id FROM bookings
  WHERE invoice_state='unknown' AND is_done=1 ORDER BY updated_at;
```

Actual local plans are retained in [MySQL](schema/invoices-mysql.json) and
[TiDB](schema/invoices-tidb.json). The first two use normalized uniqueness/number
indexes; period/state aggregation uses ix_bookings_period_invoice_state. TiDB uses
the new invoice/done/update index; MySQL chose the existing done/update index with
a state predicate on this tiny fixture. Sorting at most one booking's bounded
invoice set is acceptable. These plans verify access paths/compatibility, not
hosted cluster latency or a large-data performance claim.
