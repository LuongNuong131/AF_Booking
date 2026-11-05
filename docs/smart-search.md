# Smart search and supplier folders — Prompt 7C

Home's single Smart search field accepts booking keys, CW numbers/prefixes, stations,
station/month pairs and supplier names. It uses the exact English Prompt 1B placeholder.
Full and partial keys call `GET /bookings/lookup` directly; other input waits 200 ms
before `GET /search`. Typing cancels the old request immediately. Server `kind` remains
authoritative. Malformed key-shaped input shows `invalid_key`, without a supplier scan.

The Python and TypeScript classifiers share `fixtures/search-queries.json`, including
spaced/lowercase/dash aliases, partial keys, invalid periods and all supplied examples.
Known-station classification accepts the current station catalogue; a client without
that catalogue still calls search for the same text and uses the server result.
Every key sent to lookup/save is canonical; visible booking numbers use `display_key`.

## Home navigation

| Input | Result |
| --- | --- |
| `CW2154927-YUL-2608`, `CW 2154927-YUL-2608` | Open booking directly |
| `CW2154927-2608` | Direct lookup, then suggestion/station/ambiguity resolution |
| `CW2154927` | Folder card; select it to browse months |
| `CW2154`, `double tree`, `hilton yul` | Folder cards, relevance ordered by the server |
| `YUL` | Hotel and Transportation sections, both present |
| `YUL-2608`, `YUL 2608` | Booking rows for the station/month, including supplier identity |

Breadcrumbs retain the search/station context, folder name and current booking. `/`
focuses Smart search; arrow keys move between visible result buttons and Enter selects.
Escape goes back one level, including from Note in the left workspace; Backspace does
the same only when Smart search is empty. The explicit Clear button returns to Search.
IME composition and unrelated inputs are ignored. Active note saves block navigation;
existing per-user/key drafts are flushed before leaving the booking.

Folder cards show CW + supplier, folder icon, station, distinct supplier-type badges,
month/open counts, latest-period status/key, stale-month warning and last activity.
Latest means the greatest booking period, independent of which older month was updated
most recently. A folder shows its first 20 months, Show 20 more, and a 120-pixel windowed
list when the full folder contains over 50 months. Virtual rows use VueUse's existing
`useVirtualList`; no dependency was added.

New month uses a calendar month picker in 2000–2099 and builds
`CW…-STATION-YYMM`. It opens the existing lookup/note workspace. The folder's supplier
is known, so no new supplier form appears. Creating the booking still requires saving
a note; merely opening a new month never writes data.

A new CW without a station requires three letters before lookup can continue. A new
supplier requires a trimmed 3–255-character name and Hotel/Transportation choice;
Save stays disabled until those and the status/note requirements are met. Station and
period come from the key and display read-only. A known folder's supplier is read-only;
Admin/QC can edit it using the existing `PATCH /folders/{cw}`. Agent sees no Edit action.
A station mismatch shows the expected station and an Apply button, and blocks Save.
Both lookup metadata and the existing server `STATION_MISMATCH` error are supported.

## Summary and URLs

Summary switches between Bookings and Folders using `view=folders` in the query string.
Bookings retains all Prompt 7 filters and adds the reusable station autocomplete.
Folders uses 20-row server pages ordered by `last_activity_at`, station autocomplete,
supplier type and supplier/CW search. Query filters persist across navigation/reload.
Changing mode preserves filters and starts at page 1.

Folder cards open `/summary/folders/:cw`; month rows open the existing booking detail.
The `from` query preserves the filtered Summary or folder URL. Back to folder and Back
to Summary restore those paths. The return helper accepts only the application's
Summary/folder paths, bounded in length, without control characters/backslashes.
Booking detail also has a breadcrumb linking to its folder.

## Cache and realtime

The folders Pinia store owns a shared **50-entry LRU** for search, folder detail and
Summary folder pages. A cached value displays immediately. Reads younger than 30 seconds
reuse it; stale reads keep it visible while revalidating. Old requests are aborted on
typing/navigation and bounded by the existing eight-second search deadline, with slow
feedback at three seconds. Session and data generations prevent late responses from
restoring old data. Requests interrupted by a newer event retry once within that same
deadline. There is no polling.

`booking.updated` patches visible month status/position/agent/Done/activity immediately.
Known previous Done/stale values provide immediate count changes. The store then
debounces a **targeted GET /folders/{cw}** for watched folders to reconcile counts and
latest-period semantics. At most four such reads run together; repeated events for a
CW coalesce. Updated cards are patched across cached search/pages and recent folders.
An event does not reload `/search` or the entire `/folders` page. New/off-page membership
is filled by Refresh, returning to a stale search, or ordinary page navigation.

`FolderCard.stale_count` is an explicit additive API field, default 0, documented in
[api-contract.md](api-contract.md). It counts open months using the same status-specific
or default stale threshold as month rows. It is computed in the existing page-wide
GROUP BY query with a status join, without per-folder/per-month queries. No migration
was needed for the Prompt 7C change; the current Alembic head is maintained in
`backend/alembic/versions/` and is **0009**.

Recent folders retain at most ten supplier cards in per-user local storage. Memory and
pending reads clear on logout/session replacement; one user's history is not loaded for
another user. Home exposes recent folders and the store is ready for Prompt 8D's command
palette; Ctrl+K remains reserved for that prompt. Supplier edits update cached cards and
invalidate search immediately. Other clients see supplier edits on their next revalidation.

## Manual checks

1. Use an intended migrated development DB and a provisioned account; start Vue/FastAPI
   as described in [frontend.md](frontend.md). Test with your own existing CW/station.
2. Enter a CW, open its card and select a month. Press Escape to return to cached months,
   then Backspace in the empty search to return to results. Test arrow/Enter selection.
3. Enter a station; check Hotel and Transportation sections. Enter station + period,
   then a full spaced key; confirm canonical request keys and display-form text.
4. Enter a partial key for a known CW and apply its suggestion with Enter. Enter one
   for a new CW: require station, then supplier name/type before Save can enable.
5. Open New month from an existing folder; supplier stays read-only. Test invalid month
   and wrong station input. Use Admin/QC to rename the supplier and search the new name.
6. In Summary select Folders, filter station/type, open a folder/month and return. Reload
   at each stage to confirm URL state. Verify a narrow viewport and a folder >50 months.
7. With two users, update a watched folder's booking. Check month/card status/counts and
   the network panel: only that folder is re-read, with no full search/page reload.

Measured local integration results and reproducible commands: [testing.md](testing.md).
