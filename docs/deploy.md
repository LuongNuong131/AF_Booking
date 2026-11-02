# Deploy on Vercel, Render, and TiDB Cloud

This guide deploys the foundation, database schema, and backend authentication. It does not provision provider accounts or implement booking workflows. Run migrations and initial admin seeding explicitly. No live deployment is performed by committing these files.

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
| Start | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --no-access-log` |
| Health path | `/health` |

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

The connection pool defaults to 5 connections, no overflow, pre-ping, a 280-second recycle, and a 5-second pool/connect timeout. The ready probe has a bounded query deadline. Business query/transaction timeouts and route-specific export/note deadlines will be added with those features.

Run **one service instance and one Uvicorn worker** while auth cache invalidation/login lockouts and future realtime coordination are in memory. Multiple instances require shared coordination. Direct database changes or another process can remain cached until the 12-second TTL; admin code must use the provided invalidation/revocation helpers. A rolling deployment can briefly overlap processes, so cross-process revocation is bounded by TTL until shared invalidation exists. Configure Uvicorn's trusted proxy IPs for the actual Render proxy when needed; the app does not blindly trust client forwarding headers.

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

Run `alembic upgrade head` once as a release/pre-deploy step with the protected database settings. The initial migration creates the application tables. Do not run concurrent schema changes in every application worker. For initial admin provisioning, supply `ADMIN_USERNAME` and `ADMIN_PASSWORD` securely and run `python -m app.scripts.seed`; the seed preserves existing passwords and operator-managed status values. No default credentials exist. See [database-schema.md](database-schema.md) for provisional status rules, CHECK compatibility, and destructive rollback semantics.

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
| `VITE_API_BASE_URL` | `https://YOUR-API.onrender.com/api/v1` |
| `VITE_TIMEOUT_SCALE` | `1` (optional) |

`frontend/vercel.json` includes the SPA fallback for client-side routes. Vercel serves the static frontend only; the browser calls Render directly. WebSockets, when implemented, will connect directly to Render over WSS rather than through a Vercel serverless function.

`VITE_*` values are public and compiled into the bundle. Never put `DATABASE_URL`, database credentials, or signing keys in them. Changing the API URL requires a new frontend build. After obtaining the final Vercel domain, update Render's exact CORS allowlist and redeploy as required.

## 4. Verify the complete deployment

- Confirm both backend probes return their expected payloads.
- Open the Vercel app and verify both service cards show **Connected**.
- Reload a non-root path to verify the SPA fallback.
- Check the browser network panel for CORS errors and mixed-content requests.
- Confirm no database credentials appear in the frontend bundle or repository.

Backend authentication is implemented; verify it with the curl flow in [auth.md](auth.md) after configuring the signing secret and seeding an account. Frontend sign-in, note saving, version conflicts, idempotency, reminders, and realtime workflows still require later implementation before this is a usable booking application. Performance targets are goals, not measured guarantees.

References: [TiDB SQLAlchemy](https://docs.pingcap.com/tidb/stable/dev-guide-sample-application-python-sqlalchemy/), [TiDB MySQL compatibility](https://docs.pingcap.com/tidb/stable/mysql-compatibility/), [Render Blueprints](https://render.com/docs/blueprint-spec), [Vercel Vite](https://vercel.com/docs/frameworks/frontend/vite).
