# Project state

## Implemented: Prompt 1 deployment foundation

- Vue 3 strict-TypeScript workspace with Pinia, lazy routing, Element Plus, VueUse, Axios timeouts, date-fns, and English vue-i18n messages.
- Responsive overview showing actual API/database connectivity, explicit unavailable/unconfigured states, and retry.
- FastAPI liveness/readiness endpoints, CORS allowlist, bounded requests with cancellation, Pydantic environment validation, and production docs restrictions.
- SQLAlchemy async/aiomysql engine with verified TLS, small bounded pool, pre-ping, 280-second recycle, UTC sessions, and finite database probe deadlines.
- Alembic connection runner, dependency locks with hashes, backend/frontend tests, and GitHub Actions.
- Vercel SPA deployment configuration, Render Blueprint, and TiDB Cloud deployment instructions.

## Not implemented

Business schema and migrations, admin bootstrap, authentication/session enforcement, roles, booking lookup, folders/suppliers, note writes/history, snapshot maintenance, optimistic concurrency, idempotency, notifications, WebSockets, soft locks, reminders, invoices, reports/exports, audit, and recovery tools. Do not describe this foundation as the completed booking application.

## Next implementation steps

1. Establish the API/error/WebSocket contracts and approved status catalogue (Prompt 1B).
2. Implement and verify the TiDB-compatible schema, indexes, and Alembic migrations (Prompt 2).
3. Add authentication, admin account provisioning, authorization, and session invalidation.
4. Implement each booking/collaboration workflow in its own requested step with relevant tests.

## Deployment status

Configuration is committed for Vercel frontend, Render backend, and TiDB Cloud database. Hosted resources and credentials must be configured in those providers. A successful local test or Git push does not establish a live production deployment.
