# Operations, daily analysis and PWA — Prompt 8E

## Upgrade and configuration

Apply `.venv/bin/alembic upgrade head` from `backend`. Head **0006** adds
`daily_reports` and `push_subscriptions`, bringing the application to 16 tables.
Migrations 0001–0005 remain unchanged. No FULLTEXT index is installed automatically.
Python locks now include **pywebpush 2.5.0**; install with hash verification.
The PWA build uses Vite and Node's standard library; no additional frontend package
or API proxy is required. Hosting remains Vercel + Render + verified-TLS TiDB Cloud.

| Variable | Default / purpose |
| --- | --- |
| `APP_VERSION` | `0.2.0`; public backend release identifier |
| `DAILY_REPORT_TIME` | `18:30`, HH:mm in `BUSINESS_TIMEZONE` |
| `NOTE_SEARCH_STRATEGY` | `like`; optional `fulltext` requires supported MySQL/ngram DDL |
| `SLOW_QUERY_THRESHOLD_MS` | `200`; threshold for the SQL fingerprint collector |
| `INTEGRITY_AUTOFIX` | Existing `false`; still report-only unless explicitly enabled |
| `VAPID_PUBLIC_KEY` | Raw base64url uncompressed P-256 public point |
| `VAPID_PRIVATE_KEY` | Secret, raw base64url 32-byte private scalar |
| `VAPID_SUBJECT` | Contact `mailto:` address or HTTPS URL |

Push is disabled until all three VAPID values form a valid matching pair. The app,
REST notifications, tasks and PWA shell remain usable without them. VAPID private
keys must be real server environment values, not network-proxy placeholders or
`VITE_*` values. Never commit them or send them in chat. Generate a pair locally:

```sh
cd backend
.venv/bin/python -m app.scripts.generate_vapid --private-file /tmp/booking-vapid-private.key
```

This prints only the public key and creates a **new 0600 file** for the private key;
it refuses to overwrite an existing file. Enter the private file's contents securely
in Render's environment settings, along with the public key and a real subject.
Keep a secure backup. After key rotation, disable/re-enable push on each device so
its browser subscription is bound to the new application-server key.

## System health

Admin GET `/api/v1/admin/system/health` and `/admin/system` expose one process's live
state. Counters reset on restart and are not a multi-instance monitoring service.
Each HTTP request updates one fixed endpoint-group bucket in constant bounded work;
raw paths, booking keys, queries and body values are not retained in metrics.
Server error rate counts **5xx**, not business-validation 4xx.

Each group has thirty 30-second buckets for the last 15 minutes. p50/p95/p99 are
**approximate upper bounds** from a fixed latency histogram, explicitly marked by
`percentiles_approximate:true`. Aggregation happens on sampling/reading, not on
every request. A 120-point ring samples every 30 seconds for the one-hour sparkline.
The same independent job times a verified database `SELECT 1`, records connection
failures by class name only and reports configured pool size/checked-out/overflow,
current registered WebSockets and advisory leases. Background probes are separate
from DB-free `/health`; liveness never waits for a successful DB probe.

Scheduler jobs retain last start/finish, running flag, duration and last exception
class. Push delivery has equivalent worker state. The last error remains reviewable
after later successful executions. No exception message or note payload is retained.
The slow-query collector keeps bounded per-minute candidates over an hour and returns
the twenty longest retained executions. **Only SHA-256 SQL-shape fingerprints,
duration and observation time** are retained: literals/comments are stripped before
hashing, parameters are never read, and even normalized SQL text is not stored.

The visible System page refreshes every 15 seconds, stops/cancels while hidden or
unmounted and resumes on visibility. A global p95 above 500 ms for five sampled
minutes sets `degraded`. A new **Admin-only** `system.health {degraded}` WebSocket
event updates the Admin menu dot even when that page is closed; initial Admin
connections receive the current flag after lock.snapshot. Other roles receive no
health frames. Request/DB/job metrics remain Admin HTTP data, not socket broadcasts.

## Daily report semantics

QC/Admin GET `/api/v1/reports/daily?date=YYYY-MM-DD` returns DailyReportDTO; omitted
date defaults to today's **business** date. Future dates are rejected. Times and
day boundaries use BUSINESS_TIMEZONE, including DST. JSON timestamps are UTC;
the page formats instants in the viewer's display timezone and names the business
timezone alongside the report date.

SQL aggregates compute live note count/status/agent/station-and-Supplier-type totals.
New bookings count booking rows created within that day. Done means **distinct
bookings whose final live note at the cutoff is Done and falls within that day**,
attributed to that final agent/station/type. A booking reopened later that day is
not a final Done. The source snapshot uses MAX(live note ID), never timestamp order.
Stale/open Rejection/Parking/repeated-booking rows use that cutoff state; repeated
means at least three live notes in the day. Empty-history bookings retain nullable
agent/status. Task reporting is a count only: current pending rows created and
scheduled before the cutoff; private messages, owners and task IDs are never returned.
Past task snooze/cancellation history is not reconstructed from mutable task rows.

Generation reads a consistent **REPEATABLE READ** snapshot. Other booking/auth/write
transactions retain READ COMMITTED. Initial calculation uses the currently retained
source history/catalogue; it cannot resurrect a note deleted before generation.
After generation, past reports freeze aggregates, lists **and Daily record source
rows**, so later moderation does not change their JSON or Excel totals. Record
source is internal-only and is excluded from the JSON response/schema.

Today's report is provisional and cached for 60 seconds. At DAILY_REPORT_TIME the
scheduler persists a provisional evening snapshot. Yesterday is finalized once on
startup/next tick even before today's scheduled time, so notes added after 18:30
are included. Missing older days calculate on demand while the server is awake.
A final past row is reused directly without reading note tables again. One owned
generation lock serializes work within the supported single instance.

Large payloads use a versioned zlib/base64 envelope **inside the JSON column**, with
a readable provisional marker. This fits TiDB's row budget without truncating stale
lists or frozen record rows. Compression runs off the event loop. Normal API JSON
is unchanged. Storage limits are 128 MiB expanded / 4 MiB compressed; exceeding
them rejects generation with SERVICE_BUSY instead of silently saving a partial
report. A corrupt compressed row is rejected, not trusted as unbounded input.

GET `/api/v1/reports/daily/export?date=` downloads write-only XLSX with **Overview,
Daily record, Stale** sheets. Overview includes totals/status/agent/station/type
tables; record columns are Date, Agent, Booking, Supplier, Station, Type, Status,
Position, Note. Booking rendering honors EXPORT_BOOKING_KEY_STYLE at export time.
All user-controlled string cells receive the same formula/control-character
protection as ordinary daily export. A frozen note `=1+1` becomes `'=1+1`.
The 55-second export budget, cancellation-owned preparation, DB invalidation and
workbook/spool cleanup apply when a download times out or its client disconnects.
The `/reports/daily` page supports date selection, Excel and print CSS.

## Note search

Authenticated GET `/api/v1/search/notes` accepts q (trimmed 3–100 characters), optional
agent_id/status_code and business dates date_from/date_to, plus page/size (1/20,
size<=100). Default window is 30 inclusive calendar days; maximum is 180. A separate
60/minute/user limiter bounds this content-search path. Every strategy excludes
soft-deleted notes and uses bound parameters. Results group by booking with the
latest matching live note, match_count, agent/status/supplier/station metadata and
canonical/display keys. Page total counts bookings, not individual notes.

`NoteSearch` has explicit LIKE and FULLTEXT implementations. LIKE escapes `%`/`_`
as literal text and forces the created_at index inside the date range; it never
searches unrestricted history. **TiDB Cloud should keep the default `like`** unless
the actual chosen service/version has been separately verified for the required
FULLTEXT semantics. Local TiDB 8.5 checks verify that missing FULLTEXT returns a
clear SERVICE_BUSY rather than silently pretending it was enabled.

For supported MySQL, review and apply `backend/optional_migrations/mysql_note_fulltext.sql`
separately, then set NOTE_SEARCH_STRATEGY=fulltext and restart. The service checks
the FULLTEXT index and **ngram parser**, and rejects unsupported/missing configuration.
This optional named note index is excluded from Alembic drift removal; mandatory
indexes are still checked normally. Tests execute actual MySQL ngram searches,
including Vietnamese, and check that the optional index does not create schema drift.

Summary and the Ctrl+K palette open `/search/notes`. Query/filters/page stay in the URL.
Results use a source-preserving Unicode-aware split into text nodes and `<mark>`;
there is no `v-html`. Accent/case handling preserves decomposed accents and emoji,
and literal `<img ...>` remains text rather than executable markup.

## PWA and Web Push

The production build generates `/sw.js` from a small, reviewable worker template and
a content hash of the actual static files. Manifest, project-owned PNG icons and
Apple touch icon are included. **Only same-origin build assets, fonts, icons,
manifest and the static HTML shell are precached.** API responses, cross-origin
Render requests, mutations and arbitrary JSON are never put into CacheStorage.
Navigation uses the network with the cached shell as offline fallback. This does
not make authenticated API data available offline; existing drafts/outbox keep
their own per-user persistence and retry behavior.

Vercel serves sw.js with `no-cache, max-age=0, must-revalidate`; rewrites exclude the
worker/manifest/icons. Registration uses updateViaCache:none. A waiting version
shows the exact English `A new version is available. Reload` copy and activates
only on a click. Editors synchronously persist their newest draft before reload;
a storage failure keeps the current page/version. If another tab activates the
worker, remaining old tabs retain a working Reload prompt rather than silently
losing their draft. New first-time installations do not show an update warning.
Development Vite does not install a worker; the dedicated PWA browser check uses
the real production build/preview and verifies offline/cache/update behavior.

Authenticated push endpoints:

- GET `/push/public-key` → `{enabled,public_key:null|string}`.
- POST `/push/subscribe` → `{ok:true}` with `{endpoint,keys:{p256dh,auth}}`.
- DELETE `/push/subscribe` → `{ok:true}` with `{endpoint}`; missing own endpoint is
  idempotent, another account's endpoint is 404. Registration is idempotent for its
  owner, never transfers ownership between accounts, and is limited to ten/user.

Subscriptions validate HTTPS/provider origin, P-256 point and 16-byte auth secret.
Known production Apple/Google/Mozilla/Windows push origins are allowed; arbitrary,
private-network and credential-bearing URLs are rejected. Transport keeps TLS/proxy
trust and refuses redirects. A generated row has an extra **session_id**: sends
require an active user/current SID and opt-in, so logout/session replacement cannot
send notifications to an old signed-out device. Stale-SID rows are removed on use.
An endpoint owned by an earlier account cannot be claimed by the next account; the
browser removes its old local subscription and asks that user to enable again.

Profile's explicit Enable button is the only background-push permission entry point.
Subscribe records `users.settings.web_push_enabled=true`; disable removes that
browser subscription and clears the setting when none remain. This is separate
from foreground Web Notification preferences. Existing permission is reused;
permission is never requested on login, page load or reconnect.

After commit, task_due, assigned and watch_update notifications enter a bounded
256-item/two-worker queue **only when no active WebSocket exists**. Workers recheck
online state, active user/SID, opt-in and unchanged subscription keys before each
endpoint send. An HTTPS delivery already in flight cannot be recalled. Content contains only a
fixed title and display booking key, never note/assignment text or supplier names.
The worker validates canonical keys again, uses collapse tags and opens only a
same-origin canonical booking URL on click. 404/410 removes only the unchanged,
owned subscription; successful delivery updates last_success_at. No unbounded
retry/background job blocks a note commit. Persisted REST notifications remain the
catch-up source if a push fails or the best-effort queue is full.

The server **must be awake** to discover due tasks and emit push. Render sleep is
not solved by a service worker; waking catches up existing reminder jobs. On iOS /
iPadOS, Web Push is associated with supported Home Screen web apps (introduced in
16.4); installation, permission, device settings and actual OS/browser version
must be checked on the intended device. Linux Chromium is tested here; physical
iOS delivery and real provider delivery are not claimed by the local suite.
Reference: [WebKit's Home Screen Web Push documentation](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/).

## Verification

Run backend units/lint/generated types and frontend tests/build as in docs/testing.md.
The disposable runner adds `--suite operations` on both MySQL and TiDB. It verifies
metrics/secret-free fingerprints, report totals/frozen Excel/formula protection,
today cache/evening finalization, Vietnamese LIKE/optional MySQL ngram, ownership,
online suppression, stale/dead subscription cleanup, actual VAPID encryption with
an intercepted HTTPS transport, queue deduplication and download cancellation.
The full browser suite adds operations.mjs and pwa.mjs to the prior eight scenarios.
Live VAPID credentials/provider reachability/device permission are required for a
separate real-device push test; the tests never send messages to real subscriptions.
