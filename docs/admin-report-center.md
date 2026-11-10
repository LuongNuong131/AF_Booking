# Administration, per-booking classification and report center

## Booking classification

Each booking has its own optional classification override. Agent, QC and Admin can
choose Hotel or Transportation from the action on **each booking row** or from its
booking workspace. Unclassified imported bookings are supported. Changing one booking
does not change other months or the supplier folder's default classification.

`PATCH /bookings/{key}/classification` accepts `supplier_type` and optional
`expected_type`. A changed expected value returns 409 for review. Classification is
metadata: it preserves the note draft, note history, ownership, note/status version,
invoice declaration and operational activity timestamp. Lists, type filters, note
search and reports use `COALESCE(bookings.classification, booking_groups.supplier_type)`.
Existing bookings inherit their folder default until an override is saved. Admin/QC
retain the separate supplier-default editor.

## Administrator data management

**Admin → Data management** provides create/read/update/delete workflows for Users,
Bookings, Suppliers, Stations, Statuses, Notes, Invoices, QC tickets, Reminders, Note
snippets, Notifications and Assignments. Forms use a server-defined field allowlist,
validation and existing business services. Passwords and session secrets are never
included in record listings or recycle-bin responses.

The existing Users, Bookings and Statuses screens also have direct Delete actions.
The data console supports deleting a selected page in a batch, with an explicit
reason and per-record failure results. Removing records takes effect in operational
reads after commit; affected caches and the search index are invalidated and refreshed.

Deletion is recoverable first:

- Users/statuses retain historical identity/labels while disappearing from active
  management views. Deleted users are disabled and signed out immediately. The
  currently signed-in administrator cannot delete their own account.
- Bookings disappear from lookup/list/report workloads; their notes, invoices and
  related work are retained for restoration. Supplier/station deletion also recycles
  its active descendant folders/bookings.
- Notes are soft deleted and the booking snapshot is rebuilt. The existing note
  delete action and legacy deleted notes are included in the unified recycle bin.
- Other managed child records are archived privately for restoration. Invoice and
  note edits/deletes rebuild derived booking fields in the same transaction.

The bin supports restoration, selected permanent deletion, and **Empty recycle bin**.
Permanent deletion requires a fresh preview of the selected entries and dependent
row counts, a matching preview token and typing `DELETE`. It checks live references
under locks. A user/status still needed by retained history cannot be permanently
purged until those dependencies are removed or reassigned. Parent folders/stations
must be restored before their separately recycled children.

Permanent booking/folder cleanup removes its notes, invoices, tickets, reminders,
assignments, watches, notifications and attachment metadata. Private file deletion is
queued durably in `storage_garbage` in the same transaction. The single-instance
`storage.cleanup` job retries object-storage failures rather than losing cleanup
requests. Existing immutable audit entries remain available under the established
retention policy; operational cleanup creates its own audit trail.

A cleanup batch contains at most 2,000 recycle entries; a selected-record recycle
batch contains at most 100 records. These limits bound request/transaction work. No
endpoint clears active production data implicitly.

## Report center

Both personal and team reports use the same filtered source and export logic:

- Business-timezone day boundaries, presets and custom ranges up to 366 days.
- Personal scope for every role; team/agent selection for QC and Admin. Agent scope
  is enforced on the server for both the page and downloads.
- Filters for station, classification, final status and current invoice declaration.
- Distinct bookings worked, updates written, final completions, classification and
  invoice exceptions; participation and breakdowns by agent, status, station/type.
- Daily activity and a paginated booking detail with final note, agent, position,
  invoice metadata and timestamps. The page explains counting rules.
- Exports use the **last applied** filters and contain all matching rows, beyond the
  page on screen. A pending local filter change is shown explicitly.

Each matching booking appears once in the main detail, with its final update in the
selected date/agent scope. Agent participation counts everyone who updated a matching
booking, so participation counts may overlap. Daily activity counts notes on their
actual save dates and final booking status for each day. Current classification and
invoice metadata are read in the same repeatable-read report transaction.

Excel includes seven sheets: Executive summary, Booking detail, Agent performance,
Status distribution, Station breakdown, Supplier classification and Daily trend.
Workbooks have branded headers, numeric metrics, percentage formats, striped filterable
tables, frozen panes, wrapped notes, print titles, landscape/A4 setup, page footers,
report author/timezone/filter metadata and counting rules. CSV uses UTF-8 BOM and the
same matching details. Both formats neutralize spreadsheet formulas in user text.
Exports are capped at 50,000 bookings; larger selections must be narrowed.

## System control room

The expanded system screen shows observed component readiness, a live database probe,
request/error/latency metrics, history, process/container memory, ephemeral disk,
connection-pool capacity, runtime details, WebSocket/working-lock counts, active data
inventory, scheduled-job status/duration/errors/next run, integrity results, slow-query
fingerprints and actionable recommendations. Automatic refresh can be paused.

Metrics distinguish process-local rolling observations, approximate histogram
percentiles, optional configured services and actual database availability. Disabled
optional services are labeled explicitly. Runtime diagnostics contain no database
URLs, credentials, raw SQL or storage keys.

## What Data integrity does

It checks the booking's cached summary against its latest undeleted note and actual
invoice records. For example, a list can say Parking even though the latest note is
Done, or `invoice_count` can differ from the invoice rows. A scan records differences;
Admin reviews current/expected values and can request a repair that rechecks the
current data under row locks. It rebuilds derived summary fields and logs repairs.
The screen now explains this workflow and shows a concrete example.

## Migration and rollout

Migration **0015** adds the nullable booking override, recycle markers on operational
roots, the recycle-bin table and the durable storage-cleanup queue. Existing supplier
classifications remain the fallback; existing soft-deleted notes are enrolled in the
new recycle bin. Deploy the backend migration before the corresponding frontend.
The repository's Render pre-deploy command already runs `alembic upgrade head`.

The runtime still requires the documented single backend instance/worker. Tests run
against disposable local TLS MySQL and synthetic accounts. Production data and cloud
storage credentials are not used by the implementation session.

## Verification

See [the aggregate verification record](quality/admin-report-center-verification.json)
and [responsive browser metrics](quality/management-responsive.json). The checks cover
401 backend cases across the full run and focused regression reruns, 91.04% service
line coverage, 262 frontend unit tests, six real-API Chromium workflows and 110
management route/viewport combinations. Timing tests await actual delivery and measure
handler cancellation separately from initial route compilation.

The management database suite is included in both MySQL and TiDB CI jobs via
`python tests/run_schema_checks.py --engine mysql --suite management --report /tmp/management.xml`.
This session exercised local MySQL; TiDB and live object storage remain CI/integration
follow-ups. Screenshots and sample exported files stay outside the repository.
