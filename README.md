# Booking Tracker

An internal workspace for recording booking statuses and notes. Actual booking processing remains in the company's existing system.

**Current scope: backend through Prompt 5 and frontend through Prompt 7.** FastAPI implements authentication, booking notes/lookup/lists, Supplier/station search, private notifications, WebSocket updates, advisory locks and stale reminders. Vue now has a working Home booking workspace/My bookings list, filterable Summary, reusable booking detail/history/note entry, drafts and conflict review, alongside role guards, themes and notifications. Task UI/mutations, smart folder navigation and later features remain for their implementation prompts.

## Stack and hosting

| Component | Stack | Hosting |
| --- | --- | --- |
| Frontend | Vue 3, TypeScript, Vite, Pinia, Vue Router, Element Plus, VueUse, Axios, date-fns, vue-i18n | Vercel |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 async, aiomysql, Alembic, Pydantic 2 | Render |
| Database | MySQL-compatible TiDB, verified TLS | TiDB Cloud |

## Local development

Prerequisites: Node.js 24, npm, and Python 3.12. Run commands from this checkout; do not create another worktree for cloud tasks.

Backend, in one terminal:

```sh
cd backend
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
test -f .env || cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --workers 1 --no-access-log --ws websockets-sansio --ws-max-size 4096
```

The API can start without database/auth credentials: `/health` (also `/api/v1/health`) returns 200 without DB access, while `/api/v1/ready` returns 503 until a database is configured. Auth fails closed until `JWT_SECRET_KEY` and the database are configured. To enable login, configure the ignored `backend/.env`, migrate, and seed an Admin using protected environment values; follow [auth.md](docs/auth.md) for startup and curl examples. Never commit real credentials.

Frontend, in a second terminal:

```sh
cd frontend
npm ci
test -f .env || cp .env.example .env
npm run dev
```

The development app uses the backend at port 8000. Sign in with an operator-provisioned account. Protected routes restore the session after reload; navigation follows the current role. See [frontend.md](docs/frontend.md) for setup/API/WSS configuration and [booking-workspace.md](docs/booking-workspace.md) for Home/Summary workflows and two-browser checks. All UI copy is in `frontend/src/locales/en.json`.

## Validation

```sh
cd backend
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest -q
```

```sh
cd frontend
npm test
VITE_API_URL=https://YOUR-API.onrender.com/api/v1 npm run build
```

The production API URL must use HTTPS and end in `/api/v1`; `VITE_WS_URL` must use WSS and end in `/api/v1/ws`, or is derived when unset. Missing or invalid production configuration fails the build. Optional hosted read-only probes use `TEST_DATABASE_URL`; disposable database/browser suites use the runner documented in [testing](docs/testing.md). GitHub Actions runs the unit tests, lint, type checking, and production build.

Shared contracts: [API](docs/api-contract.md) and [WebSocket](docs/ws-protocol.md). Frontend types are generated from Pydantic schemas with `backend/.venv/bin/python scripts/generate_contract_types.py`; run the same command with `--check` to detect drift. Auth, booking and Prompt 4B search/folder/station endpoints are implemented; see [booking curl examples](docs/bookings.md) and [search/folder documentation](docs/folder-search.md).

Database migrate/seed/rollback commands, provisional status rules, index rationale, and real EXPLAIN reports: [docs/database-schema.md](docs/database-schema.md).

Deployment instructions: [docs/deploy.md](docs/deploy.md). Implementation boundaries and next steps: [PROJECT_STATE.md](PROJECT_STATE.md). Product constraints: [docs/product-context.md](docs/product-context.md).
