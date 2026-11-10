# Deploy on Vercel, Render, and TiDB Cloud

This guide covers the backend and frontend deployment. For a step-by-step Vietnamese walkthrough, including first-time setup and the free Render alternative, see [deploy-vi.md](deploy-vi.md). Provider accounts are configured by the operator. The Render Blueprint runs migrations before deployment; initial admin seeding remains an explicit operator step. Committing these files does not provision a live service.

## 1. TiDB Cloud

1. Create a cluster and select a region close to the Render service. Prefer the same region/provider where available; cross-region latency affects every query.
2. Create a `booking_tracker` database with `utf8mb4` encoding. Use a dedicated application database account. Keep credentials in Render environment settings, not GitHub, the frontend, or chat.
3. Obtain the public MySQL endpoint, port, username, and password from the connection dialog. Use the exact supplied username, including any cluster prefix. Allow the Render service's outbound IP ranges in TiDB's network access settings where required; do not open the database to all addresses as a default.
4. Build the SQLAlchemy URL below. Percent-encode the username and password individually, particularly characters such as `@`, `:`, `/`, `#`, and `%`. Do not append `ssl=false` or driver-specific TLS query parameters.

```text
mysql+aiomysql://<encoded-user>:<encoded-password>@<tidb-host>:4000/booking_tracker?charset=utf8mb4
```

`DB_SSL=true` creates a Python SSL context that verifies certificate trust and the server hostname. `DATABASE_SSL` remains a supported alias; configure consistent values if supplying both. The system CA bundle is used by default. If the cluster requires a specific CA, upload its public CA certificate as a Render secret file and set `DATABASE_SSL_CA` to that file's path. Do not upload the server private key.

TiDB supports common MySQL syntax, not every MySQL feature. Validate each future migration against the selected cluster version. Avoid triggers and stored procedures. `ascii_bin` can be used for canonical booking keys; JOIN columns must use matching character sets and collations. TiDB query plans use operators such as `Point_Get` rather than MySQL's exact `EXPLAIN type=const` output, so future performance checks must assert an indexed point lookup in TiDB's plan.

## 2. Render backend

Connect `LuongNuong131/AF_Booking` and create a Blueprint using the root `render.yaml`. Alternatively configure a Python Web Service manually:

| Setting | Value |
| --- | --- |
| Branch | `main` |
| Root directory | `backend` |
| Python | 3.12 (`PYTHON_VERSION=3.12.12` in the Blueprint) |
| Build | `pip install --require-hashes -r requirements.txt` |
| Pre-deploy (paid services) | `alembic upgrade head` |
| Start | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --no-access-log --ws websockets-sansio --ws-max-size 4096` |
| Health path | `/health` |
| Region | Singapore (`singapore`) |

The Blueprint selects Render's paid `starter` plan to avoid free-service sleep. Importing the file does not itself authorize or create a paid service; confirm the current plan and price in Render when deploying. A free service may be used for a demo, but cold starts cannot satisfy the responsiveness budget.

Required environment settings:

| Name | Value |
| --- | --- |
| `APP_ENV` | `production` |
| `JWT_SECRET_KEY` | Strong signing secret; Blueprint uses `generateValue: true` |
| `JWT_EXPIRE_MINUTES` | `720` (optional override) |
| `DATABASE_URL` | The TiDB connection URL, stored securely |
| `DB_SSL` | `true` (`DATABASE_SSL` is also supported) |
| `CORS_ORIGINS` | JSON list of exact frontend origins, for example `["https://YOUR-APP.vercel.app"]` |
| `BUSINESS_TIMEZONE` | `Asia/Ho_Chi_Minh` |

Origins must use HTTPS in production and have no path or trailing slash. Add custom domains explicitly. Arbitrary Vercel preview URLs are not automatically trusted. A Vercel preview that needs the backend must have its exact origin included intentionally, or use a separate staging backend.

The connection pool defaults to 5 connections, no overflow, pre-ping, a 280-second recycle, and a 5-second pool/connect timeout. The ready probe has a bounded query deadline. Booking lookups and note transactions have bounded query, lock and route deadlines; see bookings.md. Before tuning pool size or indexes, follow the measurement and connection-budget procedure in [database-operations.md](database-operations.md); local load figures are not a production capacity guarantee.

Run **one service instance and one Uvicorn worker** while auth cache invalidation/login lockouts and realtime connection/lock state are in memory. Multiple instances require shared coordination. Direct database changes or another process can remain cached until the 12-second TTL; admin code must use the provided invalidation/revocation helpers. A rolling deployment can briefly overlap processes, so cross-process revocation is bounded by TTL until shared invalidation exists. Configure Uvicorn's trusted proxy IPs for the actual Render proxy when needed; the app does not blindly trust client forwarding headers.

After deployment, make both requests:

```sh
curl --fail --max-time 10 https://YOUR-API.onrender.com/health
curl --fail --max-time 10 https://YOUR-API.onrender.com/api/v1/ready
```

Expected responses:

```json
{"status":"ok","service":"booking-tracker-api"}
```

```json
{"status":"ok","database":"connected"}
```

A passing liveness check alone does not prove database readiness. A 503 ready response uses `{code:"SERVICE_BUSY",message,details:{database:"not_configured"|"unavailable"}}` with `Retry-After: 5`, following [the shared API contract](api-contract.md). Investigate the connection URL, database existence, TLS trust, and TiDB network access. The API intentionally does not expose database error details publicly.

The Blueprint runs `alembic upgrade head` as its pre-deploy command, using the protected database settings. For a manually created service, configure that command or run migrations explicitly before application startup. Free services do not support pre-deploy commands or Render Shell; use the local migration/seed procedure in [deploy-vi.md](deploy-vi.md), including before future schema upgrades. Current head is **`0013`**. Do not run concurrent schema changes in multiple workers. For initial admin provisioning, supply `ADMIN_USERNAME` and `ADMIN_PASSWORD` securely and run `python -m app.scripts.seed`; the seed preserves existing passwords and operator-managed status values. No default credentials exist. See [database-schema.md](database-schema.md) and [database-operations.md](database-operations.md).

## 3. Vercel frontend

Import the GitHub repository into Vercel:

| Setting | Value |
| --- | --- |
| Production branch | `main` |
| Root directory | `frontend` |
| Framework | Vite |
| Node.js | 24.x |
| Install | `npm ci` |
| Build | `npm run build` |
| Output | `dist` |
| `VITE_API_URL` | `https://YOUR-API.onrender.com/api/v1` |
| `VITE_WS_URL` | `wss://YOUR-API.onrender.com/api/v1/ws` (optional; derived from API URL if unset) |
| `VITE_TIMEOUT_SCALE` | `1` (optional) |

Before building the frontend, wait for Render to assign its public HTTPS URL.
Set `VITE_API_URL` in **Vercel Project Settings > Environment Variables**, including
the Production environment (and Preview if you intend to use previews). Then
redeploy from the latest `main` commit. For a local production build:

```sh
VITE_API_URL=https://YOUR-API.onrender.com/api/v1 npm run build
```

The build generates `.vercel/output/config.json` and `.vercel/output/static`
using Vercel's Build Output API v3. The CSP is generated from the same validated
API, WebSocket and optional Sentry settings as the bundle. Only exact origins are
allowed. No `configure:csp` command or manual URL commit is needed. Missing API
configuration and insecure production URLs still fail the build. The example
`api.example.com` used in CI is a fixture, not a Render endpoint.

The generated routes include the SPA fallback, security headers, immutable asset caching, and service-worker/manifest cache rules. Vercel serves the static frontend only; the browser calls Render directly. WebSockets connect directly to Render over WSS rather than through a Vercel serverless function.

`VITE_*` values are public and compiled into the bundle. Never put `DATABASE_URL`, database credentials, or signing keys in them. Changing the API URL requires a new frontend build. After obtaining the final Vercel domain, update Render's exact CORS allowlist and redeploy as required.

## 4. Verify the complete deployment

- Confirm both backend probes return their expected payloads.
- Sign in with a provisioned account; verify role navigation and the **Live** realtime indicator.
- Switch theme and reload; open Profile and the notification dropdown. Sign in again from another browser context and verify the earlier session returns to Login.
- Reload a non-root path to verify the SPA fallback.
- Check the browser network panel for CORS errors and mixed-content requests.
- Confirm no database credentials appear in the frontend bundle or repository.

Backend auth and booking APIs are implemented; verify them with [auth.md](auth.md) and [bookings.md](bookings.md). WebSocket updates/locks/session logout and stale reminders are implemented; see [ws-protocol.md](ws-protocol.md). Frontend sign-in, guarded layout, notification dropdown and realtime session/reconnect handling are implemented; see [frontend.md](frontend.md). Home/Summary/booking workflows are implemented; see [booking-workspace.md](booking-workspace.md). Reminder task APIs/UI and profile preferences are implemented; see [tasks.md](tasks.md). Keep a single instance/worker while the key index, snapshot cache and session invalidation are process-local; see the cache limits in bookings.md. Performance targets are goals, not measured guarantees.

References: [TiDB SQLAlchemy](https://docs.pingcap.com/tidb/stable/dev-guide-sample-application-python-sqlalchemy/), [TiDB MySQL compatibility](https://docs.pingcap.com/tidb/stable/mysql-compatibility/), [Render Blueprints](https://render.com/docs/blueprint-spec), [Vercel Vite](https://vercel.com/docs/frameworks/frontend/vite).


Prompt 5's Render command selects the tested `websockets-sansio` backend and applies the transport byte limit from `WS_MAX_MESSAGE_BYTES` (default 4096). `uvicorn[standard]` and its WebSocket dependency are already in the verified lockfile; no dependency change is needed. The application separately enforces the byte limit. Browser clients must answer JSON `ping` with JSON `pong`; native control frames do not replace that contract. Scheduler catch-up runs on process startup, with a 20-minute stale scan, 30-second task scan and 25-second lock sweep by default. Keep exactly one running instance/worker while these are in memory; no Redis/distributed guarantees are claimed. A sleeping/stopped service cannot push, so unread notifications and read-time stale lists remain authoritative.


Daily exports default to `EXPORT_BOOKING_KEY_STYLE=display`; set `canonical` only when
an integration requires it. `EXPORT_TIMEOUT_SECONDS` defaults to 55. Frontend calls
Render directly; Vercel has no API rewrite or Functions region. The generated routes cache
hashed `/assets/` for a year with immutable, while Vite inserts API preconnect and
bundles the local Manrope font. Warmup reduces sleeping-API delay after opening Login;
it does not guarantee a free instance cold-start budget. Use one backend instance/worker
until auth caches, scheduler, locks and event coalescing are moved to shared storage.


Apply migration 0004 before deploying Prompt 8C. Existing null Rejection/Parking
reminder days become 3/2; review these in Admin statuses after upgrade. Integrity is
report-only by default, nightly at INTEGRITY_RUN_TIME=02:00 in BUSINESS_TIMEZONE.
INTEGRITY_AUTOFIX=true explicitly enables repair; the Admin page displays that mode.
Run history is durable in TiDB, but an asleep service catches up after it wakes.
See docs/safeguards-integrity.md for repair bounds and timeout settings.


Prompt 8D requires migration **0005** before application startup. No extra secret,
provider or dependency is required. Collaboration caches/locks use the same single
backend instance/worker restriction. See docs/collaboration.md for upgrade details.


Prompt 8E requires migration **0006** and the updated hash-locked Python requirements.
Set DAILY_REPORT_TIME/NOTE_SEARCH_STRATEGY as needed; leave LIKE on TiDB Cloud unless
the actual provider/version is separately verified for FULLTEXT/ngram compatibility.
For live Web Push, set real matching VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY/VAPID_SUBJECT
in Render (never VITE_*), deploy the frontend over HTTPS and opt in from Profile.
No VAPID value is generated or committed as a production secret by the test suite.
Vercel must preserve the generated worker/manifest/icon rewrite exclusions and
sw.js no-cache headers. See operations-pwa.md for key generation, sleep/iOS limits,
rotation, static-only caching and verification. No provider deployment is implied
by Git push or a saved development-environment draft.


Prompt 8F requires migration **0007** before starting the new API. Existing invoice
declarations remain intact; unset bookings stay unknown. No new secret/dependency
is needed. Review INVOICE_NUMBER_PATTERN and INVOICE_MAX_PER_BOOKING (default 20);
lookup sends the same rules to the frontend. See invoices.md for rollback, immutable
past-report compatibility, exact search and the shared offline PUT queue.


Prompt 9 requires migration **0008** (new `users.must_change_password`). Seeded, newly
created and reset accounts must change their temporary password before accessing
business APIs or WebSocket. Existing accounts which have never signed in are marked
for rotation; accounts with previous logins retain their current state. Seed reruns
do not reset a completed rotation. Passwords are 10–128 characters and cannot equal
the username; login still accepts legacy passwords up to 1024 characters so those
users can rotate. Production startup rejects a missing, short or known-default JWT
secret. `JWT_SECRET` is accepted as an alias of `JWT_SECRET_KEY`; supply one only.

Body limits default to `MAX_REQUEST_BODY_BYTES=1048576`; WebSocket defaults are
`WS_MAX_MESSAGE_BYTES=4096`, `WS_MAX_MESSAGES_PER_SECOND=20` and
`WS_SEND_TIMEOUT_SECONDS=5`. WebSocket Origin must be in the same exact CORS list;
native diagnostic clients must send Origin too. API personal responses use no-store.
`style-src 'unsafe-inline'` supports Element Plus and virtual-list dynamic styles;
scripts remain external, without unsafe-inline/unsafe-eval. See security-report.md
for storage tradeoffs, dependency audit evidence and verification commands.

## Prompt 10 optional production settings

Migrate through **0012** before this version starts. Keep one API worker/instance.
Backend `SENTRY_DSN` and frontend `VITE_SENTRY_DSN` are optional; leave blank to
disable them. When enabling frontend Sentry, set `VITE_SENTRY_DSN` in Vercel and
redeploy. The build adds only the configured Sentry origin to its generated CSP.
Production URL validation still rejects insecure endpoints. Use `/health` for Render liveness; `/health/db`
is a separately throttled DB probe. Retention defaults and external alert routing
are in [observability.md](observability.md). Configure encrypted backup secrets
and opt-in scheduling only after database provisioning; see [backup.md](backup.md).
