# Booking Tracker

An internal workspace for recording booking statuses and notes. Actual booking processing remains in the company's existing system.

**Current scope: deployment foundation.** The repository contains a working Vue workspace, FastAPI health/readiness endpoints, verified-TLS TiDB connectivity, an Alembic runner, tests, and deployment configuration. Authentication, business tables, booking operations, and WebSocket events are not implemented yet. The overview page reports service connectivity; it does not display invented bookings or offer unfinished actions.

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
cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API can start without a database. `/api/v1/health` returns 200 when the process is running; `/api/v1/ready` returns 503 with `code: SERVICE_BUSY` and `details.database: not_configured` until a database is configured. Configure `DATABASE_URL` in `backend/.env` using TiDB Cloud's connection details to enable readiness. Do not commit this file.

Frontend, in a second terminal:

```sh
cd frontend
npm ci
cp .env.example .env
npm run dev
```

The development page uses the backend at port 8000. All UI copy is in `frontend/src/locales/en.json`; routes load asynchronously. Frontend API requests have finite timeouts, connection checks can be retried, and loading state is released in `finally`.

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
VITE_API_BASE_URL=https://YOUR-API.onrender.com/api/v1 npm run build
```

The production URL must use HTTPS and end in `/api/v1`. Missing or invalid production configuration fails the build. Database integration tests require `TEST_DATABASE_URL`; see [testing](docs/testing.md). GitHub Actions runs the unit tests, lint, type checking, and production build.

Shared contracts: [API](docs/api-contract.md) and [WebSocket](docs/ws-protocol.md). Frontend types are generated from Pydantic schemas with `backend/.venv/bin/python scripts/generate_contract_types.py`; run the same command with `--check` to detect drift. Business routes are reserved in the contract and remain unimplemented.

Deployment instructions: [docs/deploy.md](docs/deploy.md). Implementation boundaries and next steps: [PROJECT_STATE.md](PROJECT_STATE.md). Product constraints: [docs/product-context.md](docs/product-context.md).
