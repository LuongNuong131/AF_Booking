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
