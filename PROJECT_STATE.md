# Project state

## Implemented: Prompt 1 deployment foundation

- Vue 3 strict-TypeScript workspace with Pinia, lazy routing, Element Plus, VueUse, Axios timeouts, date-fns, and English vue-i18n messages.
- Responsive overview showing actual API/database connectivity, explicit unavailable/unconfigured states, and retry.
- FastAPI liveness/readiness endpoints, CORS allowlist, bounded requests with cancellation, Pydantic environment validation, and production docs restrictions.
- SQLAlchemy async/aiomysql engine with verified TLS, small bounded pool, pre-ping, 280-second recycle, UTC sessions, and finite database probe deadlines.
- Alembic connection runner, dependency locks with hashes, backend/frontend tests, and GitHub Actions.
- Vercel SPA deployment configuration, Render Blueprint, and TiDB Cloud deployment instructions.

## Not implemented

Authentication/session enforcement, permission checks, booking lookup, folder/supplier services, note writes/history APIs, snapshot maintenance, optimistic concurrency, idempotent write services, notifications, WebSockets, soft locks, reminders, invoice services, reports/exports, audit recording, and recovery tools. Do not describe this foundation as the completed booking application.

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

## Next implementation steps

1. Confirm the provisional Position/note-required status rules when the business mapping is available.
2. Add authentication, authorization, and session invalidation APIs (Prompt 3).
3. Implement each booking/collaboration workflow in its requested step, preserving Prompt 1B.

## Deployment status

Configuration is committed for Vercel frontend, Render backend, and TiDB Cloud database. Hosted resources and credentials must be configured in those providers. A successful local test or Git push does not establish a live production deployment.
