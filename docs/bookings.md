# Booking backend — Prompt 4

The API now supports lookup, notes/history, mine/overall/stale lists, active statuses and private notifications. It also implements Admin/QC supplier-folder edits needed by cache invalidation. No user endpoint edits or deletes an existing note. WebSocket broadcast remains an internal no-op; attachment storage deliberately returns 501. Frontend screens are not part of this backend prompt.

## Run and migrate

From `backend`, configure the ignored `.env` as described in [auth.md](auth.md), then:

```sh
.venv/bin/alembic upgrade head
.venv/bin/python -m app.scripts.seed --statuses-only
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log
```

Migration `0002` adds nullable note fingerprint/result columns. Existing notes remain readable. Only new writes have a replayable original response. Position labels remain provisional; newly seeded Rejection/Parking statuses require a note. Seed preserves existing Admin edits, so existing deployments must enable those two flags if they retained the earlier false defaults.

## Call the API

Use the token obtained from [the login flow](auth.md), provided through a protected `ACCESS_TOKEN` shell variable; do not commit real tokens. Example booking/supplier data below is fictitious.

```sh
curl --fail-with-body --max-time 10 -G http://localhost:8000/api/v1/bookings/lookup \
  -H "Authorization: Bearer $ACCESS_TOKEN" --data-urlencode 'key=cw 2154654 - rdu - 2609'

curl --fail-with-body --max-time 15 http://localhost:8000/api/v1/bookings/CW2154654-RDU-2609/notes \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  --data '{"status_code":"BUNDLE","note":"Waiting for supplier response.","expected_version":0,"client_request_id":"f6830c72-2b18-4c04-8a4e-a90d94c05a01","supplier_name":"Example Hotel","supplier_type":"hotel"}'

curl --fail-with-body --max-time 10 http://localhost:8000/api/v1/bookings/mine \
  -H "Authorization: Bearer $ACCESS_TOKEN"

curl --fail-with-body --max-time 10 -G http://localhost:8000/api/v1/bookings/stale \
  -H "Authorization: Bearer $ACCESS_TOKEN" --data-urlencode 'scope=all'

curl --fail-with-body --max-time 10 http://localhost:8000/api/v1/notifications \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Generate a fresh UUID for every intended new note. Retrying the same operation must retain its UUID and payload; the example returns the first response on retry. For another note, use the latest snapshot version as `expected_version`. For Done, add `invoices:{"add":["INV-001"]}` or `invoices:{"no_invoice":true}` when still undeclared. For cursor history, pass the returned `history.next_cursor` unchanged to `/bookings/{key}/notes?cursor=...&limit=20`.

Detailed envelopes and reserved later-prompt behavior: [api-contract.md](api-contract.md#booking-implementation-details--prompt-4).

## Index, cache and deadlines

Use **one process/worker and one service instance**. The key index/cache are process-local, not a distributed consistency mechanism. Index bootstrap runs in background with keyset batches, retaining concurrent post-commit additions/edits. Until ready or with `KEY_INDEX_ENABLED=false`, exact lookup uses UNIQUE `booking_key` and partial lookup uses `(cw_number,period)`. When ready, missing full keys return without any booking DB access; authentication can still query when its own cache expires.

Reconciliation compares booking/folder COUNT/MAX(id) and folder MAX(updated_at) every 600 seconds. It reloads after changes or failures. Direct database edits can be stale until reconciliation; count/max does not detect an in-place booking-key rewrite. Supported writes never rewrite a booking key. Run `key_index.load()` internally or restart after out-of-band identity repairs. Folder updates through the API update the index immediately. Multiple service replicas require shared invalidation before enabling this index.

Snapshot LRU stores at most 2,000 entries for 30 seconds, with a generation guard against repopulating from an older concurrent read. It never stores history or private tasks; stale age is recomputed on every cache hit. A successful commit invalidates before any broadcast await. Folder edits invalidate all cached bookings in that folder. Historical note attachments are fetched in one batch, invoice previews use one windowed query and task counts use one GROUP BY for the page; none are queried once per item.

Business transactions use READ COMMITTED plus explicit user/group/booking row locks. User/session is rechecked inside note/folder writes. Uniqueness/deadlock races get one retry, optimistic conflicts return 409 and lock-wait 1205 returns 503. Cancellation rolls back/discards its connection; cleanup is shielded from a second cancellation. All requests have a finite ASGI deadline, and both retry attempts fit inside the save budget. A lost response after commit is recovered by the durable UUID result.

MySQL connections get `max_execution_time`; MariaDB gets `max_statement_time`. Unknown/unsupported-variable errors alone fall back to the asyncio deadline. Lock waits use `innodb_lock_wait_timeout`; a server execution timeout on `SELECT ... FOR UPDATE` is also returned as 503 contention, since MySQL can reach that limit just before an equal lock-wait limit. TLS verifies certificate chain and hostname. WARNING timeout logs contain route, budget and request ID, never note text.

| Variable | Default |
| --- | --- |
| `REQUEST_TIMEOUT_SECONDS` / `LOOKUP_TIMEOUT_SECONDS` | 8 / 6 |
| `NOTE_SAVE_TIMEOUT_SECONDS` / `EXPORT_TIMEOUT_SECONDS` | 12 / 55 |
| `DB_QUERY_TIMEOUT_MS` / `DB_LOCK_WAIT_TIMEOUT_SECONDS` | 5000 / 5 |
| `DB_CONNECT_TIMEOUT_SECONDS` / `DB_POOL_TIMEOUT_SECONDS` | 5 / 5 |
| `KEY_INDEX_ENABLED` / `KEY_INDEX_BATCH_SIZE` | true / 1000 |
| `KEY_INDEX_RECONCILE_SECONDS` | 600 |
| `SNAPSHOT_CACHE_MAX_ENTRIES` / `SNAPSHOT_CACHE_TTL_SECONDS` | 2000 / 30 |
| `STALE_HOURS_DEFAULT` | 24 |
| `STATION_CODE_PATTERN` | `[A-Z]{3}` (ASCII, storage limit 4) |
| `INVOICE_NUMBER_PATTERN` / `INVOICE_MAX_PER_BOOKING` | `[A-Z0-9_./-]{3,40}` / 20 |

The Python parser and `frontend/src/utils/bookingKey.ts` run the same `fixtures/booking-keys.json` cases. Parser input is capped at 128 characters; raw control-bearing keys are invalid, while `normalize` is independently usable to strip them. Zero-width format characters are removed. Partial keys can resolve existing/future months but cannot create data. Legacy invalid keys are read-only.

## Verification

From `backend`:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite booking --report /tmp/booking-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite booking --report /tmp/booking-tidb.xml
```

Each database suite runs in an isolated, TLS-verified Docker container and removes it afterward. Tests cover real API writes, contention, UUID replay, ownership, supplier/station rules, cursor ties/deletion/attachments, batched lists, stale thresholds, warm-index zero-query misses, UNIQUE lookup plans, cancellation rollback/discard, SELECT SLEEP timeouts, lock waits, exhausted pools and recovery after a post-commit response timeout. [testing.md](testing.md) also describes schema/auth suites and frontend checks.
