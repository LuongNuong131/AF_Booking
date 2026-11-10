# Folder, Supplier and station search — Prompt 4B

This adds backend APIs to the existing schema/auth/booking service. No UI screens or database migrations are added. All endpoints require an active bearer session. Existing Admin/QC `PATCH /folders/{cw}` remains the single supplier-edit path; only Admin can name stations.

## Query classification and results

`GET /api/v1/search?q=...&page=1&size=20` checks in this order:

| Input | Classification | Response kind |
| --- | --- | --- |
| `CW2154927-YUL-2608`, `cw 2154927 - yul - 2608` | Full key | `booking` |
| `CW2154927-2608`, `CW 2154927-2608` | Missing station | `partial_key` |
| `CW2154927`, `CW2154927-YUL` | Exact CW (5–10 digits) | `folder`, or `none` |
| `CW2154` | CW prefix (fewer than 5 digits) | `folders`, or `none` |
| `YUL-2608`, `yul 2608` | Station/period | `station_period`, or `none` if station is unknown |
| `YUL`, `yul` | Existing station | `station` |
| `Hotellus`, `double tree`, `hilton yul` | Supplier words | `folders`, or `none` |

`CW` alone is also a folder prefix. An optional station after a CW constrains the result; the wrong station produces `none`. Five or more digits are an exact CW, including when no folder exists: they do not silently become a prefix. Invalid key-shaped input (for example a month 13) yields `none`, without a Supplier LIKE scan. An unknown three-letter code is Supplier text, as the station classification requires an existing station row. An existing station with zero folders returns `station`, two empty sections and `total:0`.

The response always has `kind` and `query`. Query is normalized to uppercase, compact whitespace and standard hyphens; full/partial keys use canonical spelling. Shapes and explicit additions are in [api-contract.md](api-contract.md#folder-search-implementation-details--prompt-4b). Search page sizes are 1–20; page numbers are 1-based. Empty input returns `{kind:"none",query:"",items:[]}`. No-result key lookup still returns `booking` with `exists:false`, while unresolved partial keys preserve their resolution.

Supplier normalization uses the existing `normalize_supplier_name`: remove diacritics (`đ`→`d`), replace punctuation with word boundaries, case-fold and collapse spaces. Every query word must prefix at least one Supplier word, in any order: `tree doub` matches `Double Tree`, and `eto hot` matches `Hôtel Étoile`. `d/b/a`, `&` and hyphens become separators. Ranking is exact normalized name, whole-query name prefix, word matches; recent folder activity and ID break ties within each rank. Folder list pages retain activity ordering instead of relevance ordering.

## Folder and station APIs

- `GET /folders/{cw}` returns `{folder:FolderCard,months:MonthRow[]}` with **all** months, ordered `period DESC,id DESC`. Folder latest means the largest period, with highest booking ID breaking legacy duplicate-period ties; inserting an older month later does not make it latest. Counts come from actual bookings, including the number not Done. Empty folders have zero counts and `latest:null`.
- `GET /folders?page&size=20&station_code&supplier_type&q` returns `{items,total,page,size}` sorted by `last_activity_at DESC,id DESC`. Size is 1–100. `q` accepts Supplier words or CW/prefix; an optional CW station qualifier and explicit station filter must agree. Other key-shaped inputs return an empty page. Supplier type is `hotel` or `transportation`.
- `PATCH /folders/{cw}` accepts supplier name/type/recurrence for Admin/QC. Every booking role can independently classify a booking through `PATCH /bookings/{key}/classification`. Name normalization, audit, snapshot invalidation and the shared index update happen through the Prompt 4 service; successful changes are searchable immediately.
- `GET /stations?q=` returns `[{code,name,folder_count}]`, ordered by code, with code-prefix matches before station-name-word matches. Name matching ignores accents. Empty `q` returns all station entries. This catalogue includes stored station rows even when their folder count is zero.
- `PATCH /admin/stations/{code}` accepts `{name:string|null}`, Admin only. Names have at most 100 input characters; controls are cleaned and whitespace collapsed; null/blank clears the name. The station must already exist (404 otherwise). Station creation remains part of first-folder note saving. Rename is audited and immediately invalidates station cache.

Station autocomplete caches its database result for 60 seconds. `ETag` hashes the filtered representation, `If-None-Match` (including weak validators) returns bodyless 304 when unchanged, and `Cache-Control: private, max-age=60` applies. Auth is still checked before returning 304. New folders invalidate counts, including with `KEY_INDEX_ENABLED=false`; additional months of an existing CW do not change folder count. CORS permits `If-None-Match` and exposes `ETag`.

## Indexes, limits and fallback

Supplier fields are added to **the existing KeyIndex GroupEntry**, alongside ID/CW/station/type/activity. There is no second Supplier index. Bootstrap uses the existing background keyset loader and retains concurrent post-commit updates. Reads scan the 2,000-folder RAM metadata and page the ranked IDs before fetching display data. Folder creation, note activity and supplier edits update that same entry after commit. This remains a **single-instance, single-worker** design; shared Redis coordination belongs to Prompt 12.5.

When KeyIndex is not ready or disabled, Supplier lookup uses ANDed word-prefix LIKE predicates against `booking_groups.supplier_name_normalized`. Leading-word predicates can use its prefix index; internal-word fallback can scan folder metadata and is bounded by the three-second budget. Full keys use UNIQUE `booking_key`, partial keys `(cw_number,period)`, exact CW its UNIQUE constraint, station folders the station/type/activity index, and station/period bookings `(station_code,period)`. Those booking-key branches never use LIKE.

For one displayed page, one SQL query groups the selected booking group IDs on `(group_id,period)` to produce count, open count and latest month, joining the latest booking/status/agent. It does not query once per folder and never joins note history. Folder detail adds one all-month query. No history or private task data is exposed by search.

| Setting | Default |
| --- | --- |
| Maximum `q` length | 100 characters |
| Search page size | 20 (maximum 20) |
| `SEARCH_MAX_REQUESTS` | 120 per authenticated user |
| `SEARCH_RATE_WINDOW_SECONDS` | 60 |
| `SEARCH_RATE_MAX_ENTRIES` | 10000 users; active limits are not evicted to admit another user |
| `SEARCH_DB_TIMEOUT_SECONDS` | 3 (maximum 3); bounds the whole search execution/fallback |
| `STATION_CACHE_TTL_SECONDS` | 60 (maximum 60) |

The outer search route keeps the six-second lookup budget, including authentication. Deadline expiry is 504 `REQUEST_TIMEOUT`; rate exhaustion is 429 `RATE_LIMITED` with `Retry-After`. The rate limiter and cache are process-local, like KeyIndex. Direct database edits are reflected on cache expiry/reconciliation; supported API writes invalidate immediately.

## Run, call and test

Use the existing [auth startup](auth.md) and [booking setup](bookings.md). Apply the latest Alembic head (`0003` after Prompt 7B). Supply a token via the protected `ACCESS_TOKEN` shell variable; example data below is fictitious.

```sh
curl --fail-with-body --max-time 10 -G http://localhost:8000/api/v1/search \
  -H "Authorization: Bearer $ACCESS_TOKEN" --data-urlencode 'q=double tree'
curl --fail-with-body --max-time 10 -G http://localhost:8000/api/v1/search \
  -H "Authorization: Bearer $ACCESS_TOKEN" --data-urlencode 'q=YUL-2608'
curl --fail-with-body --max-time 10 http://localhost:8000/api/v1/folders/CW2154927 \
  -H "Authorization: Bearer $ACCESS_TOKEN"
curl --fail-with-body --max-time 10 -i http://localhost:8000/api/v1/stations \
  -H "Authorization: Bearer $ACCESS_TOKEN"
curl --fail-with-body --max-time 10 -X PATCH http://localhost:8000/api/v1/admin/stations/YUL \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  --data '{"name":"Montreal"}'
```

From `backend`, with Docker available:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite folder --report /tmp/folder-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite folder --report /tmp/folder-tidb.xml
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite search-performance --report /tmp/search-mysql.json
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite search-performance --report /tmp/search-tidb.json
```

These runners create and remove their own disposable databases and TLS certificates. Performance fixtures are inserted as snapshots directly; no real company data or hosted credentials are used. CI also checks booking/auth regressions, generated wire types, and the frontend build; the new response union has a required `kind` discriminator.

## Measured p95

The goal is p95 below 100 ms at 2,000 folders/50,000 bookings. The recorded benchmark uses 10 query classes, three warmups then 60 sequential samples each, one ASGI worker, and a real verified-TLS loopback database. It includes auth dependency/cache, classification, SQL and response serialization. It excludes public HTTP/TLS/hosting latency and concurrent production traffic.

| Database | Largest per-query p95 | Index bootstrap |
| --- | --- | --- |
| MySQL 8.0.46 | 20.072 ms | 1012.318 ms |
| TiDB 8.5.0 (local unistore) | 51.356 ms | 1120.717 ms |

Every measured query class met the 100 ms target in this local run. These measurements are not a hosted Render/TiDB Cloud SLA. Reports include all samples' p50/p95/max summaries and EXPLAIN evidence for page aggregation, station folders and station/period: [MySQL report](performance/search-mysql.json), [TiDB report](performance/search-tidb.json). The benchmark test asserts the same p95 goal and index usage and runs in CI.
