# Project state

## Implemented: Prompt 1 deployment foundation

- Vue 3 strict-TypeScript workspace with Pinia, lazy routing, Element Plus, VueUse, Axios timeouts, date-fns, and English vue-i18n messages.
- Responsive overview showing actual API/database connectivity, explicit unavailable/unconfigured states, and retry.
- FastAPI liveness/readiness endpoints, CORS allowlist, bounded requests with cancellation, Pydantic environment validation, and production docs restrictions.
- SQLAlchemy async/aiomysql engine with verified TLS, small bounded pool, pre-ping, 280-second recycle, UTC sessions, and finite database probe deadlines.
- Alembic connection runner, dependency locks with hashes, backend/frontend tests, and GitHub Actions.
- Vercel SPA deployment configuration, Render Blueprint, and TiDB Cloud deployment instructions.

## Not implemented

Frontend sign-in/booking screens, full invoice management/reports, WebSocket transport, soft locks, reminder mutations, assignments/watch, exports, and recovery tools. Do not describe this as the completed booking application.

## Implemented: Prompt 1B shared contract

- `docs/api-contract.md` records all endpoint paths, request fields, access rules, pagination shapes, error codes, and explicit clarifications. `docs/ws-protocol.md` reserves the exact event names and directions; runtime frames/payloads remain for their implementation prompt.
- Pydantic wire models define booking snapshots, invoices, notes, statuses, tasks, suggestions, folders, months, key resolution, and pagination. Frontend TypeScript types are generated from these schemas; CI rejects stale generated files.
- HTTP errors use top-level `code`, `message`, and optional `details`, including validation, not-found, timeout, readiness, and internal errors. CORS and Retry-After headers are retained where applicable. Validation responses do not echo input secrets.
- English copy from Prompt 1B is stored with the supplied keys and interpolation variables. Status labels do not replace the Admin-managed status catalogue.
- `Task` and `FolderCard.latest` include `display_key` to satisfy the universal key/display rule.

## Implemented: Prompt 2 database schema

- Eleven SQLAlchemy mapped models, matching initial Alembic migration, InnoDB/utf8mb4 defaults, binary ASCII keys, unsigned IDs, and UTC DATETIME(3).
- Required indexes, with explicit ID tie breakers for TiDB ordered scans; no database foreign keys, duplicate booking-key index, or hash index.
- Canonical-key CHECK where enforcement is available, ORM storage validation fallback, and supplier-name normalization.
- Repeatable status and environment-supplied Argon2id admin seeding. Missing real admin credentials remain an operator configuration requirement.
- MySQL/TiDB disposable TLS tests verify migration parity, seeds/CLI, constraint behavior, eight index plans, the folder JOIN, rollback, and re-migration. Actual reports and assumptions are in docs/database-schema.md.
- Prompt 1B invoice/status/notification storage additions are retained without implementing their APIs.

## Implemented: Prompt 3 auth and authorization

- Four `/api/v1/auth` endpoints with Argon2 passwords, HS256 JWTs, configured token lifetime, generic failed-login errors, and no registration route.
- Single-device SID enforcement, active-user checks, bounded 12-second user/session cache, and immediate same-process invalidation on login/logout/password/kick/disable.
- Shared `get_current_user`, `require_roles`, database-session dependency, and authoritative rechecks for critical session mutations.
- Per-IP/account five-failure lockouts, safe request-ID logging/headers, DB-free `/health`, atomic auth audit records, and no-store auth responses.
- Internal `kick_session` / `set_user_active` helpers and an injectable `session.force_logout` transport placeholder; no admin HTTP API or WebSocket runtime yet.
- Unit tests plus disposable MySQL/TiDB auth integration suites, including cache/ACLs, concurrent login/password/logout scenarios, audit rollback, and transport failure.
- `JWT_SECRET_KEY` is an operator requirement; Render Blueprint can generate it. No default signing key/password is stored.

## Implemented: Prompt 4 booking backend

- Canonical/partial key parsing in Python and TypeScript using shared JSON fixtures.
- Exact/partial/ambiguous lookup, supplier reuse/station guards, active statuses and required note validation.
- Append-only note transaction with row locks, optimistic versions, atomic takeover notifications/audit and inline invoice changes.
- Durable UUID replay of the original response, migration `0002`, one retry for duplicate/deadlock races and authoritative session rechecks.
- Cursor history with batch attachment metadata, mine/overall/stale pages, batched private task counts and notification ownership.
- Startup keyset RAM index, periodic reconciliation, DB fallback, generation-guarded snapshot LRU and post-commit invalidation before the broadcast stub.
- Pure ASGI route deadlines, SELECT/lock/pool timeouts, cancellation rollback/connection discard, Server-Timing and safe WARNING logs.
- Admin/QC folder supplier edit and intentional NullStorage 501 attachment interface.
- Disposable TLS MySQL/TiDB booking tests added to CI; run instructions and explicit envelope clarifications in docs/bookings.md and docs/api-contract.md.

## Implemented: Prompt 4B folder/Supplier/station search

- Ordered query classification: full booking, partial key, exact CW, CW prefix, station/period, existing station, Supplier text. Key-shaped branches never run Supplier LIKE queries.
- Seven typed `/search` result variants, all-month folder detail, paginated/filtered folder list and immediate Admin/QC supplier edits.
- The existing KeyIndex GroupEntry now stores normalized Supplier words/activity; prefix-of-every-word matching ranks exact, starts-with, words, then recent activity. There is no separate Supplier index.
- Page-wide booking-count/open-count/latest-period aggregate uses the group/period index, with no per-folder queries. Station and station/period use existing indexes.
- Authenticated station autocomplete has a 60-second generation-guarded cache, ETag/304, private caching and Admin naming/audit. New folders and station renames invalidate station metadata.
- Search has a 100-character limit, per-user 120/minute sliding window and a dedicated three-second database fallback deadline.
- MySQL/TiDB tests cover classification, word/diacritic matching, rename visibility/ACL/audit, pagination, no-LIKE key branches, one-query aggregates and station caching. A reproducible 2,000-folder/50,000-booking benchmark verifies p95 and EXPLAIN plans; reports and limits are in docs/folder-search.md.
- Search wire types are generated as a discriminated union. No frontend screens or new database migrations were added.

## Next implementation steps

1. Confirm the provisional Position labels when the business mapping is available.
2. Add Admin APIs using the provided role checks and session-invalidation helpers when requested.
3. Continue later prompts for task mutations, frontend screens and realtime.

## Deployment status

Configuration is committed for Vercel frontend, Render backend, and TiDB Cloud database. Hosted resources and credentials must be configured in those providers. A successful local test or Git push does not establish a live production deployment.
