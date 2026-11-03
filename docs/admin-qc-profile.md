# Admin, QC and Profile (Prompt 8)

Admin pages are `/admin/users`, `/admin/audit`, `/admin/bookings`, `/admin/trash`,
`/admin/statuses` and `/admin/suppliers`. Reports are `/reports` for Admin/QC.
Every active user can open `/profile`. Both router guards and backend dependencies
check roles; critical mutations also lock and recheck the actor's current SID/role
inside the transaction. No schema migration is needed beyond `0003`.

## Accounts and audit

User creation accepts username, display name, role and a 12–1024-character temporary
password. Hashing runs in the bounded password thread pool. Lists expose `has_session`
without returning a SID, password hash or personal settings. Disable, reset password,
role change and End session revoke the old session/cache and notify its socket.
An Admin cannot disable or demote themselves. An account is re-enabled explicitly;
its old session remains revoked. Creation, edits, access changes, password resets,
kicks, status changes, note moderation, Supplier/Station edits and exports are audited.
Passwords and task messages never enter audit metadata.

Audit filters support user, action, entity type/ID and aware UTC date boundaries;
the UI converts the user's local filter times to UTC. Metadata renders as escaped
compact JSON. Earlier audit rows may have null entity fields.

## Moderating notes and statuses

Bookings & notes reuses the booking table and opens paginated complete history,
including deleted notes. Delete requires a 3–255-character reason and confirmation.
Trash shows the author, deletion actor/time/reason and a confirmed Restore action.
Admin operations wait for the committed server response; they have no optimistic UI.

Delete/restore locks group, booking and note in that order after authenticating the
actor, then rebuilds from the latest surviving note by `(created_at,id)`. It restores
last status, stored position, agent and preview; Done time is that note's original
creation time. With no surviving notes these fields and Done time become null.
The booking/folder and invoices remain. Every effective mutation increments version,
updates activity time, resets the stale notification marker, invalidates snapshots,
updates the shared index, then publishes `booking.updated`. Repeated delete/restore
of an already-matching state is a no-op.

Status editing supports all flags plus default task days and invoice requirement.
Disable a used status instead of deleting it. Changed position labels affect future
notes; historical notes retain their saved position. Changing `is_done` rebuilds
current booking Done flags/times and increments their versions without changing the
last operational update time. `catalog.updated` invalidates active clients' catalogue
and snapshots, so new statuses/labels become available without reloading the app.

## Reports and downloads

Performance aggregates exclude deleted notes. Date ranges use `BUSINESS_TIMEZONE`,
with inclusive local dates and exclusive next-day UTC boundaries. Defaults are today,
Monday through today, or month start through today; custom ranges are at most 366 days.
`done_count` counts currently Done bookings whose `done_at` is in the selected range,
attributed to the current final agent; it does not count repeated Done transitions.
Daily trend and status distribution count notes. Stale and overdue-task blocks are
current totals. Stale uses the same predicate as `/bookings/stale`. Task reports expose
counts/agents only, with no private task text, IDs, booking keys or reminder times.
Seven SQL aggregates run under a bounded transaction; reports use a 45-second LRU cache.
Admin catalogue/moderation changes invalidate it; ordinary writes expire within TTL.
Chart.js loads only when rendering charts.

Daily export filters by business date, optional agent and status. Its exact columns
are Date, Agent, Booking, Supplier, Station, Type, Status, Position, Note. Date includes
the business UTC offset; Booking defaults to the display key. Set
`EXPORT_BOOKING_KEY_STYLE=canonical` to export canonical keys instead. Internal queries
always use canonical keys. Deleted notes are excluded and positions are historical.

CSV streams UTF-8 with BOM in 500-row batches. XLSX uses openpyxl `write_only`, spools
at 2 MiB and serializes in a worker thread. Leading `=`, `+`, `-`, `@`, tab or newline
is prefixed with an apostrophe, including formulas after leading spaces. Invalid XML
controls are removed. Export uses `EXPORT_TIMEOUT_SECONDS` (55 seconds by default).
Disconnect/cancellation invalidates the unbuffered DB connection before closing its
cursor; partial workbook files are cleaned. Once CSV headers are sent, a timeout
ends the stream instead of replacing it with JSON. The export audit records initiation.

## Suppliers, stations and personal profile

Admin can search/paginate folders and stations, edit suppliers, open their months and
name stations. Existing folder PATCH refreshes the same supplier/key index. QC edits
suppliers from folder pages; QC has no Admin routes.

Profile can change display name, password, IANA timezone, default reminder time,
weekend skipping, sound and opt-in Web Notifications. Changing a password ends the
current session. Browser permission is requested only on explicit opt-in. Personal
counts use the profile timezone (today / Monday-through-now), and recent login history
contains only the owner's login/session audit records.

## Manual verification

1. Create an Agent as Admin; sign in as that Agent in a second browser. End its session,
   then disable/enable it and reset its password. Attempt self-disable/self-demotion.
2. Add two notes, ending in Done. Delete the last note with a reason, then restore it
   from Trash. Observe another browser's snapshot update and verify invoices remain.
3. Change a status label/create a status; the other browser's note form updates live.
4. As QC, compare report counts and daily CSV/XLSX, including a business-midnight note
   and `=1+1`. Check that `/admin/users` is blocked.
5. Change profile name/timezone and password; verify own statistics and new login.
