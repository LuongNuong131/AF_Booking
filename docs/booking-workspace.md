# Home, Summary and booking detail (Prompts 7–7C)

Prompt 7C extends lookup with smart supplier-folder search and month navigation; see
[smart-search.md](smart-search.md) for the current field, breadcrumbs and Summary folder mode.

Home now has a booking workspace and a live **My bookings** list. Summary is a
server-paginated overview with shareable filters; its detail route reuses the same
summary, activity and note components. All visible copy is English, including error
codes and the shared Prompt 1B messages. [frontend.md](frontend.md) covers setup and
public API/WSS environment variables.

## Home workflow

1. Focus **Booking number** (automatic initially, or `/`). Paste a full/display key,
   then press Enter. Blur/Enter formats a valid full key for display; API calls keep
   the canonical key. A new query cancels an earlier lookup and cannot lose newly
   typed input to a late response.
2. A partial key calls the same lookup API. A resolved suggestion uses the snapshot
   already returned, without a second request; Enter applies it. Ambiguous matches
   offer explicit choices. A new CW requires a three-letter station, with station
   autocomplete, before the full lookup. No note can save against an unresolved key.
3. Check the large booking number, Supplier/type, station, period, current status,
   Position, latest agent and zoned timestamp. Done and another user's advisory lock
   are warnings. Activity is newest-first with its latest entry highlighted; each
   explicit **Load more activity** fetches at most 20 rows. The activity pane scrolls
   to keep the note form reachable.
4. Select the dynamic status (`Alt+1…5` follows `sort_order`), enter a note if required,
   and save with **Save update** or Ctrl/Command+Enter. Position is read-only. Save
   takes a fresh UUID for each intended operation and retains the same UUID/payload
   for an uncertain manual retry. It never auto-retries a mutation. The in-flight
   guard blocks double saves; note input remains editable and newer typing is kept.
5. A committed save updates the snapshot/history and list, clears only the submitted
   draft, releases the lease and focuses Booking number. A version conflict opens a
   review dialog with the latest note; **Use latest version and keep my draft** sets
   the new expected version. It does not automatically send the note. A further
   save uses a new UUID because its expected-version payload changed.

The workspace owns its lease: acquire after lookup/selection, renew through the
shared 30-second transport heartbeat, release after save/clear/query change or leaving
its scope. A denial never disables writing. Reconnect reacquires the current lease.
Foreign updates set a refresh banner; they do not replace the draft. Explicit
refresh, reconnect and hidden-tab refresh can reload snapshot/history while retaining
status/note fields. An update arriving during the initial read is also detected.

Drafts are keyed by authenticated user ID and canonical booking key in localStorage,
debounced 500 ms, expire after seven days, and are bounded to 100 entries per user.
They restore on opening the same key and disappear after save or **Discard draft**.
The mounted draft remains editable offline; Save stays disabled until online.
Storage failure is reported and the in-memory note remains available. A pending
POST is not an outbox: automatic/durable resend is reserved for Prompt 8B.

Two minimal fields support creating the first booking of a new Supplier folder:
Supplier name and Hotel/Transportation. Prompt 7C implements smart folder/Supplier
lookup; see [smart-search.md](smart-search.md). The backend's Done status requires
an invoice declaration; when needed,
the form accepts invoice numbers or an explicit **No invoice Number** checkbox via
`NoteSaveRequest.invoices`. These fields only support the existing note-save contract.
Separate invoice editing, duplicate-elsewhere warnings, reports and the full Prompt
8F interface remain unimplemented. No invoice declaration is invented automatically.

## My bookings and realtime

The right list uses `/bookings/mine?page&size=10`. Selecting a row opens it in the
left workspace. **Stale (N)** switches to `/bookings/stale?scope=mine`; age comes from
the returned stale state/hours. Prompt 7B adds the Task tab and working reminder
buttons; see [tasks.md](tasks.md).

A foreign update removes a row that moved to another agent, with a short transition.
A self update on page 1 hydrates the affected booking and moves it to the top; on
later pages it increments a deduplicated new-items counter instead of moving the
page. Clicking that counter returns to page 1. Small event-driven count reads keep
the normal/stale totals authoritative; there is no timer polling. Refresh can fill
holes left by removed rows.

`booking.updated` intentionally omits Supplier and note preview. `useBookingRows`
patches the known fields immediately, then fetches only affected bookings through
`useRequest`. It coalesces queued work by key, bounds the queue, rejects older
versions and never re-inserts an old own snapshot after a later takeover. Events
arriving during a page request replay against the returned page. Stale state comes
from the hydrated API snapshot rather than assuming a status-specific threshold.

## Summary and detail

- Summary uses `/bookings`, 20 rows per page, `updated_at_desc`, with stable row keys.
  The table scrolls horizontally on small displays; the page remains within the
  viewport. No large dataset is downloaded for local pagination.
- Search debounces 300 ms and cancels the previous request immediately. A full key is
  canonicalized; a partial key becomes `cw_number` + `period`. Other text searches
  booking prefixes, stations and normalized Supplier names on the server.
- Status, Agent, Station, Type, Period, Supplier, date range, completion and stale
  filters persist in the URL. The Agent directory search uses the small authenticated
  `/users/lookup` API. Existing/inactive agents visible in the page remain selectable.
- Dates and **Today** use `users.settings.timezone`, including daylight-saving day
  boundaries, before conversion to UTC query timestamps. Reversed date ranges and
  a partial-key/month conflict require correction before another API request.
- Clicking a row opens its canonical `/summary/:key` with a validated Summary return
  path. **Back to Summary** restores the same filters/page. Detail supports the same
  note form and Activity; direct links fall back to unfiltered Summary on return.
- Realtime updates/hydrates only visible rows and reorders those rows by timestamp.
  A row that no longer matches known filters is removed, with a refresh option to
  fill the page. Page boundaries and the full result total refresh on explicit read;
  the browser never fetches the entire page for every event.

The Pinia booking store caches at most 50 short read responses for 12 seconds and
keeps the status catalogue for 60 seconds. Events/saves invalidate booking reads;
logout/session replacement clears private cache and remembered Home selection.
Session generations prevent older responses from entering the next user's cache.
No debounced search/autocomplete can navigate or start another request after its
view is disposed. All requests retain local slow/timeout/error/Retry feedback.

## Manual check with two browsers

Use two **distinct**, active, provisioned accounts. Two logins to one account test
forced logout instead of collaboration. Start the backend with one instance/worker
and verified database settings; start Vite as in frontend.md.

1. In browser A, open a booking, choose a status and start a note. In browser B,
   open the same booking; B should see A's advisory working tag.
2. Save a different note in B. The booking leaves A's My bookings and appears at
   the top of B's. A gets an update banner and retains its text.
3. Save A's old version. Review B's latest note in the conflict dialog, keep A's
   draft, then save again. The booking moves back to A and both histories agree.
4. Write another draft, wait for **Draft saved**, reload and reopen the same key.
   Confirm restoration, then discard. Go offline while editing: Save disables and
   text stays; go online and confirm the draft survives reconnect.
5. In Summary, combine filters, open a row and return. The URL/filter/page should
   match. While Summary remains open, save a visible booking in B; that row updates
   without a `/bookings` page reload.
6. On My bookings page 2, make a self update elsewhere and check the new-items
   counter. Test the Stale chip against a genuinely stale booking. Check light/dark
   themes and keyboard focus on desktop and mobile widths.

Automated coverage includes these two-browser flows against disposable TLS TiDB,
plus unit tests for deadlines, drafts, UUID retries, cache/session invalidation,
request/realtime races, pagination, filters and unmount cleanup. See testing.md.
