# Collaboration — Prompt 8D

## Upgrade and storage

Run `.venv/bin/alembic upgrade head` from `backend` before starting this version.
Head is **0005**; migrations 0001–0004 are unchanged. The migration adds
`booking_watchers`, `booking_assignments`, and notifications.merged_count (unsigned
SMALLINT, default 1). Notification enum values were already reserved by 0001;
0005 explicitly retains the complete required enum without rewriting that migration.

Watchers have composite primary key (booking_id,user_id) and user/created index.
Assignments have recipient/status/created, sender/status/created and booking indexes.
A nullable generated open_to_user_id with unique (booking_id,open_to_user_id)
enforces one open assignment per recipient/booking even under concurrent requests.
The extra nullable decline_reason stores the requested reason. Notifications use a
nullable generated unread_watch_booking and unique (user_id,unread_watch_booking)
to merge only unread watch_update rows. Read/other notification types never collide.
These generated unique indexes are verified on MySQL and TiDB. Downgrade drops the
new collaboration data/columns; it leaves the pre-existing enum values intact.

## Watch API and delivery

- PUT/DELETE `/api/v1/bookings/{canonical_key}/watch` returns `{watching:boolean}`.
  Both are idempotent; missing bookings return NOT_FOUND, malformed paths
  INVALID_BOOKING_KEY. A user-row lock serializes subscription counting: maximum
  200, with WATCH_LIMIT_REACHED on an explicit addition beyond the cap.
- GET `/api/v1/watching?page=1&size=10` returns the owner's Page<BookingItem>, latest
  activity first. BookingItem adds private my_watching (also in lookup snapshots).
  Cached shared snapshots never include another user's watch flag. List pages batch
  watch flags and personal pending-task counts in one aggregate query.
- Profile accepts `settings.auto_watch_on_note` (default false). When true, a
  committed note adds a subscription in that same transaction, if there is room.
  Auto-watch at the cap is best effort: it does not block an operational note.
  NoteSaveResponse adds private `my_watching`, retained with its UUID replay response.
  The client reconciles this flag after replay/overlapping watch changes rather than
  restoring an obsolete subscription choice.

A note reads watcher IDs once, excluding its author. A watcher who was the previous
agent gets taken_over only, rather than a second watch_update for that note.
All new takeover/watch/assignment notices use one multi-row INSERT. Its unique-key
upsert replaces by_agent_id/note_id/created_at and increments merged_count for an
existing unread watch_update. The counter saturates at 65,535 instead of overflowing.
After a read, a later update creates a new ID with count 1. A single indexed metadata
read retrieves resulting IDs. No notification is sent before commit. Online sockets
receive notification.new; disconnected users catch up through GET /notifications.
Inactive users' saved subscriptions remain; they cannot authenticate or receive new
sessions, and can unwatch after being reactivated.

Both notification REST items and socket payloads add merged_count (default 1 for old
payload compatibility). Merged socket events keep the same notification ID. The
client refreshes that item without increasing the unread badge; unread means rows,
not merged note count. Assignment notices remain distinct workflow events even when
the same recipient also follows the booking.

## Assignments

Note saves accept optional positive assign_to and assign_message (at most 255
characters). The actor and recipient user locks are acquired in sorted ID order;
the actor's live SID and recipient's active flag are rechecked before saving.
Self/inactive/missing recipients, messages without recipients and an existing open
assignment return ASSIGNMENT_INVALID. A failure rolls back the note and all effects.
UUID replay returns the original result without recreating assignments/notices.

Creation uses the saved note ID and sends assigned to the recipient. Any subsequent
note by that recipient on this booking completes their open assignment atomically
and sends assignment_done to its sender. Soft-deleting that note later does not
reopen the completed workflow. Assignment message and decline reason are plain text.

GET `/api/v1/assignments?view=to_me|from_me&status=open|done|declined&page=1&size=10`
returns Page<AssignmentItem>; defaults are to_me/open. Omitting status uses open;
each view is restricted to the caller's own incoming/outgoing work. Items contain
id, note_id, canonical/display keys, from_user/to_user {id,full_name}, message,
status, created_at, resolved_at, decline_reason. POST `/{id}/complete` and
POST `/{id}/decline {reason}` return that item; only its recipient can mutate it
(others receive 404, including unrelated Admin). Decline requires nonblank text up
to 255 characters. Repeating the same resolution has no extra notification/audit;
trying the other outcome after resolution returns ASSIGNMENT_INVALID. Decline is
recorded in history/audit and does not invent an additional notification type.

`GET /users/lookup?q=&limit=20` remains a minimal active-user directory containing
only id/full_name. It allows 120 requests/minute/user, q<=100, limit<=50 and a bounded
10-second process-local cache. Admin edits/profile name changes invalidate the cache;
note saves still recheck the actual recipient row. No session/settings/hash fields
are exposed.

Home adds Assigned to me (open incoming count) and Watching tabs. Incoming/outgoing
and resolved-status filters are available in Assignments. Counts catch up on
login/reconnect/visibility, private assignment events and committed personal notes;
no polling is added. Watching patches displayed booking rows on realtime updates.
Completion/decline/watch operations wait for the server and prevent duplicate clicks.
Assignment fields survive draft/outbox reload and business-error restoration.

## Palette and keyboard

Ctrl+K / Cmd+K loads the palette chunk on demand, including from an input. `/`
continues to focus booking search. Full and partial booking inputs normalize before
lookup; a full booking appears first as Open booking {display_key}. Command search
is client-side fuzzy matching. Navigation respects role: Admin only for Admin;
Reports/daily export only for QC/Admin. Theme, sign-out, current-booking Task and
Watch/Unwatch are supported. Daily XLSX export resolves BUSINESS_TIMEZONE from the
authorized report API and exports that business date, with the existing deadline
and formula protections. Command filtering never calls the API.

Ten canonical recent booking keys are persisted per user in localStorage; recent
Supplier folders reuse the existing per-user folder history. Sign-out clears active
private stores; switching accounts never displays another account's recent items.
Search notes is explicitly disabled until Prompt 8E supplies its API/view; no fake
search endpoint or unrelated navigation is presented as note search.

useShortcuts centrally dispatches keydown by scope, warns in development about duplicate
keys in a scope and disposes registrations. BookingTable, My bookings, TaskList,
notifications and assignments use J/K or arrows, Enter, W, T and [/] paging. A row's
roving tabindex is 0 only for the selected row. Input/textarea/select/contenteditable,
IME/composition, repeated keys and open help/Task/palette dialogs are excluded from
list shortcuts. Virtual table navigation reveals an off-screen row before focusing it.
Enter on an action button retains its native action. Notifications page ten rows
within the existing 20-item feed; the API's limit contract stays unchanged. `?`
opens the extended help. Browser Ctrl+K is intentionally overridden by the palette.

## Checks

From repository root:

```sh
backend/.venv/bin/python backend/tests/run_schema_checks.py --engine mysql --suite collaboration --report /tmp/collaboration-mysql.xml
backend/.venv/bin/python backend/tests/run_schema_checks.py --engine tidb --suite collaboration --report /tmp/collaboration-tidb.xml
BOOKING_CHROMIUM_PATH=/usr/bin/chromium backend/.venv/bin/python backend/tests/run_schema_checks.py --engine tidb --suite frontend --report /tmp/browser.xml
```

Mutating suites use disposable verified-TLS databases only. Collaboration checks
cover fanout/one INSERT, merged ID/count/read reset, takeover deduplication, private
watch flags, watch cap/idempotence, active-recipient guards, note rollback, automatic
and manual resolution, decline/reassignment, UUID replay, directory rate limits and
real private WebSocket frames. Vitest covers list scope/typing/focus/actions, command
role/fuzzy rules, watch request state, merged badges, private recent history and
assignment draft/payload persistence. Chromium adds three-user collaboration and
real palette/keyboard interactions to the existing browser regression suite.
