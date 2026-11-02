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

The initial implementation was also checked against a local TiDB v8.5.0 container using `unistore`, loopback-only access, a private test CA, a server certificate with matching IP/hostname, and mandatory TLS. This is a development test configuration; TiDB Cloud uses its own deployment and certificates. The Alembic runner was executed against the isolated database to verify its connection path. There are no business migrations yet.

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
