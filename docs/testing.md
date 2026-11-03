# Testing

Run the backend unit suite from `backend` with `.venv/bin/python -m pytest -q`. Tests verify readiness failure/success, CORS, request cancellation and its elapsed deadline, TLS verification configuration, production restrictions, and database pool configuration. Contract tests also verify UTC millisecond serialization, nullable fields, required display keys, pagination, sanitized validation errors, domain statuses, safe internal errors, and preserved response headers. Two integration tests are skipped unless `TEST_DATABASE_URL` is set; skipped tests are not database validation.

To validate a real TiDB connection, use an isolated test database. Supply connection settings through your terminal's secure environment or a secrets manager; do not paste credentials into commands committed to Git.

- `TEST_DATABASE_URL`: a `mysql+aiomysql` URL for the test database.
- `TEST_DATABASE_SSL_CA`: optional public CA bundle path. System roots are used when absent.

```sh
cd backend
.venv/bin/python -m pytest tests/test_tidb_integration.py -q
```

These integration tests make read-only probes, assert that the negotiated TLS cipher is nonempty, verify the UTC session timezone, and confirm the ASCII binary collation needed by booking keys. They do not exercise business migrations, data writes, or hosted TiDB Cloud networking.

The foundation was checked against a local TiDB v8.5.0 container using `unistore`, loopback-only access, a private test CA, a server certificate with matching IP/hostname, and mandatory TLS. TiDB Cloud uses its own deployment/certificates. Prompt 2 adds a separate mutating schema check and initial migration; see [database-schema.md](database-schema.md).

To test migrations, admin/status seed repeatability, query plans, rollback, and re-migration, run from `backend`:

```sh
.venv/bin/python tests/run_schema_checks.py --engine mysql --report /tmp/explain-mysql.json
.venv/bin/python tests/run_schema_checks.py --engine tidb --report /tmp/explain-tidb.json
```

Docker is required. The runner creates a uniquely named disposable database/container and temporary TLS certificates, then cleans them up. `tests/test_schema_database.py` is skipped during the ordinary unit run unless the runner supplies `SCHEMA_TEST_DATABASE_URL`; this variable explicitly designates a disposable writable database. Never point it at a persistent application database. CI runs this workflow separately for both engines and uploads the reports.

Prompt 3 auth integration checks run separately in fresh databases:

```sh
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite auth --report /tmp/auth-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite auth --report /tmp/auth-tidb.xml
```

These exercise real database transactions through the ASGI auth endpoints, including one-device session replacement, inactive accounts, role guards, cached-session invalidation/TTL, rate-limit aliases, password/logout races, audit rollback, and transport failure. `tests/test_auth_database.py` is skipped without the runner's explicit disposable database configuration. Unit coverage includes JWT signature/expiry/claim validation, hashing cancellation bounds, request IDs, and database-free `/health`. See [auth.md](auth.md) for endpoint contracts, startup configuration, and curl examples.

Frontend checks, from `frontend`:

```sh
npm test
VITE_API_BASE_URL=https://api.example.com/api/v1 npm run build
```

Vitest verifies readiness response handling, production URL validation, the visible failed-connection/retry flow, recognized error envelopes, and interpolation of every shared English UI string. The build includes strict Vue/TypeScript checking and route splitting. It uses an example URL only for build validation; use the real Render URL for deployment.

From the checkout root, verify generated wire types with `backend/.venv/bin/python scripts/generate_contract_types.py --check`. Backend schemas are authoritative; regenerate types after intentional schema edits. CI runs this check so stale frontend types cannot pass the workflow.

To update Python locks intentionally, install `uv`, edit `requirements.in` or `requirements-dev.in`, then run:

```sh
uv pip compile requirements.in --generate-hashes --quiet -o requirements.txt
uv pip compile requirements-dev.in --generate-hashes --quiet -c requirements.txt -o requirements-dev.txt
```

Reinstall with hash verification and rerun affected checks. Frontend installation uses the committed `package-lock.json` and `npm ci`.

Prompt 4 adds shared Python/TypeScript booking-key fixtures and cache tests. Real booking API checks use fresh TLS databases:

```sh
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite booking --report /tmp/booking-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite booking --report /tmp/booking-tidb.xml
```

These verify row-lock/version races, original-response UUID replay after later writes and post-commit timeout, required notes, supplier/station/partial-key rules, private takeover notifications/tasks, cursor ties/deleted notes, stale thresholds, zero-query indexed misses, folder invalidation, batch list queries, EXPLAIN point lookup, cancelled rollback/connection discard, pool exhaustion and lock-wait 503. CI runs schema, auth and booking suites for both engines and uploads reports. Full startup/curl/configuration: [bookings.md](bookings.md).

Verification for the Prompt 4 implementation: **87 backend unit tests passed**; 44 integration tests were skipped in that ordinary run and executed separately where applicable. On **each** disposable MySQL 8.0 / TiDB 8.5 database, **25 booking tests + 16 auth tests + 1 schema/migration/EXPLAIN test passed**. Frontend: **48 Vitest tests passed**, strict type checking and production build passed. Ruff checks/format and generated-contract drift checks passed. The two optional hosted-TiDB probe tests remain skipped because no hosted test connection was supplied; local Docker results do not prove hosted deployment readiness.

Prompt 4B adds classification/index/limiter unit tests and real folder/search/station suites:

```sh
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite folder --report /tmp/folder-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite folder --report /tmp/folder-tidb.xml
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite search-performance --report /tmp/search-mysql.json
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite search-performance --report /tmp/search-tidb.json
```

Folder tests verify all result variants, exact CW versus prefix, all-month ordering/backfills, counts, station/type pagination, accent/punctuation/multiple-word matching, ranking and immediate rename/audit/ACL, TTL/ETag/304/auth, zero-folder stations, no-LIKE key branches, one-query page aggregates, rate limits, and the separate DB deadline. The benchmark creates 2,000 folders/50,000 bookings and checks index plans and warm sequential ASGI p95 below 100 ms. Committed reports and measurement limits are in [folder-search.md](folder-search.md). The post-commit retry test now expires its HTTP deadline after the broadcast hook is reached, so it tests the intended committed-write race without assuming a contended TLS transaction will finish within 100 ms.

Prompt 4B verification: **114 backend unit tests passed** (66 database tests skipped in that unit run). Separate disposable MySQL and TiDB runs each passed **21 folder/search/station tests, 25 booking tests, 16 auth tests and one 2,000-folder/50,000-booking performance/index-plan test**. Frontend remained at **48 passing tests**, strict TypeScript and production build passed. Ruff and generated-contract checks passed. Hosted provider probes remain unrun without an explicit hosted test connection.

Prompt 5 adds realtime manager/lease/scheduler/token-redaction unit checks and real TCP WebSocket peers:

```sh
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite realtime --report /tmp/realtime-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite realtime --report /tmp/realtime-tidb.xml
```

These use the installed Uvicorn `websockets-sansio` backend on a loopback-only listener and the same isolated verified-TLS databases. They verify two-user post-commit updates and fresh lookup, private takeover/stale events, advisory denial/save/expiry/disconnect, same-SID replacement, new login and revocation helpers, actual 4401 close codes, fresh-row handshake checks, JSON ping/pong/idle close, invalid/binary/oversize messages, no duplicate replay events, stale thresholds/batch markers and immediate scheduler catch-up. The ordinary DB fixtures explicitly disable background jobs for isolation; the catch-up test starts the registered scheduler and observes its immediate event. Unit tests separately simulate a permanently blocked sender, bounded queue overflow, SID targeting and failure isolation. These tests establish local protocol/transaction behavior, not hosted Render WSS readiness. See [ws-protocol.md](ws-protocol.md).

Prompt 5 verification: **122 backend unit tests passed**, with 86 database tests skipped in that ordinary run. Separate disposable MySQL and TiDB runs each passed **20 real WebSocket/stale tests, 25 booking regressions and 16 auth regressions**. Frontend: **48 tests**, strict types and production build passed. Ruff/format and generated frame/type drift checks passed. No new migration or dependency lock change was needed. Hosted WSS/provider probes remain unrun without a configured hosted deployment.
