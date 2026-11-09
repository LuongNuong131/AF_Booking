# AF Booking

> A focused operations workspace for tracking booking status, notes, ownership, invoices, and team activity — without trying to replace the system that actually processes bookings.

[![CI](https://github.com/LuongNuong131/AF_Booking/actions/workflows/ci.yml/badge.svg)](https://github.com/LuongNuong131/AF_Booking/actions/workflows/ci.yml)
[![Frontend](https://img.shields.io/badge/frontend-Vue%203%20%2B%20TypeScript-42b883?logo=vuedotjs&logoColor=white)](frontend)
[![Backend](https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white)](backend)
[![Database](https://img.shields.io/badge/database-TiDB%20%2F%20MySQL%20compatible-4479A1?logo=mysql&logoColor=white)](docs/database-schema.md)
[![License](https://img.shields.io/badge/license-private%20project-15232B)](#project-status)

AF Booking is an internal, multi-role booking operations console for teams that need a reliable answer to three questions:

- What is the current state of this booking?
- Who owns the next action?
- What changed, when, and by whom?

The application is intentionally narrow. Booking creation and the underlying business transaction remain in the company’s existing system. AF Booking provides the operational layer around that workflow: fast lookup, structured notes, history, collaboration, reminders, invoices, reporting, and auditable administration.

---

## Contents

- [Product overview](#product-overview)
- [What is included](#what-is-included)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Local development](#local-development)
- [Configuration](#configuration)
- [Testing and quality gates](#testing-and-quality-gates)
- [UI quality and performance](#ui-quality-and-performance)
- [Deployment](#deployment)
- [Security model](#security-model)
- [Operational boundaries](#operational-boundaries)
- [Documentation map](#documentation-map)
- [Project status](#project-status)

## Product overview

### Built for operational clarity

AF Booking keeps the main workflow deliberately compact:

1. Search by booking key, CW number, station, period, or supplier.
2. Open the canonical booking workspace.
3. Review the latest snapshot and append a note with the correct status.
4. See history, ownership, tasks, invoices, and realtime activity in context.
5. Hand off work without losing the audit trail.

### Designed for real team usage

The product supports Agent, QC, and Admin roles, with authorization enforced on the backend. It is designed for teams of roughly 20–100 staff and data sets containing tens of thousands of bookings. Lists are paginated, routes are lazy-loaded, realtime messages are incremental, and the UI avoids full-page blocking states during ordinary requests.

## What is included

### Booking workspace

- Canonical booking-key normalization and validation.
- Exact, partial, ambiguous, and station-assisted lookup.
- Smart search across booking keys, CW numbers, stations, periods, and supplier names.
- Supplier folders with station and monthly booking navigation.
- Append-only notes with status, position, ownership, and optimistic version checks.
- Activity timeline with cursor pagination.
- Draft persistence, conflict review, duplicate-note protection, and offline outbox recovery.
- My bookings, stale bookings, summary filters, and live list updates.

### Collaboration and productivity

- Advisory booking locks with realtime presence signals.
- Booking watches, assignments, takeover notifications, and private notifications.
- Private reminder tasks with due alerts, snooze, and booking navigation.
- Command palette and scoped keyboard shortcuts.
- Light, dark, and system theme modes, including an eye-comfort dark palette with no pure-white surfaces.
- Responsive workspace shell for desktop and smaller screens.

### Administration and operations

- Role-aware Admin, QC, Reports, Profile, and system-health screens.
- User, session, supplier, station, status, audit, trash, and integrity workflows.
- Invoice declarations, validation, search, reconciliation, exports, and repair tooling.
- Daily CSV/XLSX reports with business-timezone boundaries.
- Bounded request, database, WebSocket, and scheduler deadlines.
- Optional Sentry integration, retention controls, encrypted backup tooling, and PWA/Web Push support.

> Attachment storage is intentionally left behind a `501` interface until an S3-compatible provider is configured. Redis-backed multi-instance coordination and external Telegram/email notifications are not part of the current deployment model.

## Architecture

```text
┌──────────────────────────────┐
│  Vue 3 / TypeScript / Vite   │
│  Pinia · Router · Element Plus│
│  Vercel static frontend       │
└──────────────┬───────────────┘
               │ HTTPS / WSS
┌──────────────▼───────────────┐
│  FastAPI / Python 3.12       │
│  Auth · bookings · realtime  │
│  tasks · reports · admin      │
│  Render web service           │
└──────────────┬───────────────┘
               │ TLS MySQL protocol
┌──────────────▼───────────────┐
│  TiDB Cloud                   │
│  MySQL-compatible persistence │
└──────────────────────────────┘
```

| Layer | Technologies | Responsibility |
| --- | --- | --- |
| Frontend | Vue 3, TypeScript, Vite, Pinia, Vue Router, Element Plus, VueUse, Axios, date-fns, vue-i18n | Workspace UI, guarded navigation, drafts, optimistic interactions, realtime client |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 async, aiomysql, Alembic, Pydantic 2 | Auth, authorization, booking workflows, reports, tasks, audit, WebSocket transport |
| Database | TiDB Cloud, MySQL-compatible protocol | Durable booking snapshots, notes, users, tasks, invoices, audit and operational data |
| Delivery | Vercel, Render, GitHub Actions | Static frontend, API service, CI, schema checks, browser checks, optional backups |

### Data and consistency principles

- Booking keys are stored canonically as `CW{number}-{STATION}-{YYMM}`.
- Notes are append-only; booking snapshots are updated in the same transaction.
- `expected_version` protects against stale writes, while `client_request_id` makes retries replay-safe.
- Realtime is an acceleration and collaboration layer, never the source of truth.
- The current production shape is one backend instance and one worker while process-local auth, cache, scheduler, lock, and event state remain in memory.

## Repository layout

```text
.
├── backend/                 # FastAPI application, Alembic, tests, locked requirements
│   ├── app/                 # API, services, models, auth, realtime, jobs
│   ├── alembic/             # Database migrations
│   └── tests/               # Unit, database, realtime, security and performance suites
├── frontend/                # Vue application and Vite configuration
│   ├── src/components/      # Shared UI and booking components
│   ├── src/views/           # Routed screens
│   ├── src/stores/          # Auth, bookings, tasks, realtime, UI and caches
│   ├── src/composables/     # Requests, shortcuts, refresh and navigation helpers
│   └── src/locales/         # User-facing copy
├── docs/                    # Contracts, workflows, deployment and operations guides
├── fixtures/                # Shared booking, invoice and search fixtures
├── scripts/                 # Contract generation, backup and utility scripts
├── render.yaml              # Render backend blueprint
└── PROJECT_STATE.md         # Evidence-backed implementation status and boundaries
```

## Local development

### Prerequisites

- Node.js 24.x and npm.
- Python 3.12.
- A MySQL-compatible database for authenticated flows and integration tests.
- TLS database settings for TiDB Cloud or another compatible provider.

The health endpoint can run without database credentials. Authenticated application flows require a configured database and `JWT_SECRET_KEY`.

### 1. Start the backend

```sh
cd backend
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
test -f .env || cp .env.example .env

.venv/bin/python -m uvicorn app.main:app \
  --reload \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --no-access-log \
  --ws websockets-sansio \
  --ws-max-size 4096
```

The liveness endpoint is available at `http://localhost:8000/health`. Readiness remains unavailable until the database is configured. For migrations and an operator-provisioned Admin account, follow [docs/auth.md](docs/auth.md) and [docs/database-schema.md](docs/database-schema.md).

### 2. Start the frontend

In a second terminal:

```sh
cd frontend
npm ci
test -f .env || cp .env.example .env
npm run dev
```

Open `http://localhost:5173`. The default local API and WebSocket endpoints are:

```dotenv
VITE_API_URL=http://localhost:8000/api/v1
VITE_WS_URL=ws://localhost:8000/api/v1/ws
```

There is no public registration flow and no default password. Sign in with an account provisioned by an operator.

## Configuration

### Frontend variables

| Variable | Description |
| --- | --- |
| `VITE_API_URL` | API base URL ending in `/api/v1`; required for production |
| `VITE_WS_URL` | WebSocket URL ending in `/api/v1/ws`; derived from the API URL when omitted |
| `VITE_TIMEOUT_SCALE` | Positive multiplier for client request deadlines; defaults to `1` |
| `VITE_SENTRY_DSN` | Optional public Sentry DSN |

Production frontend URLs must use HTTPS/WSS. `VITE_*` values are public bundle configuration; never place credentials, database URLs, JWT secrets, or private keys in them.

### Backend essentials

Configure these in the backend environment, Render, or your secret manager — never in Git:

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Runtime mode, `production` for hosted deployment |
| `JWT_SECRET_KEY` | JWT signing secret |
| `DATABASE_URL` | MySQL/TiDB connection URL |
| `DB_SSL` | TLS verification switch |
| `CORS_ORIGINS` | Exact allowed frontend origins |
| `BUSINESS_TIMEZONE` | Business reporting timezone, normally `Asia/Ho_Chi_Minh` |

See [backend/.env.example](backend/.env.example) and [docs/deploy.md](docs/deploy.md) for the complete configuration surface.

## Testing and quality gates

### Frontend

```sh
cd frontend
npm run lint
npm run test:security
npm test

VITE_API_URL=https://api.example.com/api/v1 \
VITE_WS_URL=wss://api.example.com/api/v1/ws \
npm run build
```

### Backend

```sh
cd backend
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python ../scripts/generate_contract_types.py --check
.venv/bin/python -m pytest -q
```

GitHub Actions also runs dependency audit checks, contract drift checks, disposable MySQL/TiDB schema suites, security suites, frontend tests, and browser coverage. The full evidence and environment requirements are documented in [docs/testing.md](docs/testing.md).

## UI quality and performance

The frontend is treated as an operations console: clarity and response time take priority over decorative effects. The UI uses a restrained visual system, lightweight transitions, CSS containment on dense surfaces, stable scroll regions, responsive touch targets, and route-level lazy loading. No new UI dependency is added for the visual layer.

### Dark Mode

Dark Mode is designed for long working sessions rather than maximum contrast:

- Soft blue-grey page and surface tones instead of pure black or white.
- Teal accents with readable contrast and calmer hover states.
- Theme-aware Element Plus dialogs, popovers, dropdowns, inputs, tables, and selection colors.
- `prefers-contrast: more` support for users who need stronger separation.
- `prefers-reduced-motion` support and no heavy animation pipeline.
- Theme color is applied before the first render and updated when the user switches theme, reducing light flashes on dark devices.

### Lighthouse production baseline

The following scores were measured against the production bundle served through `vite preview` on the root/login route. This is a frontend baseline; authenticated booking routes require a session and are not represented here.

| Profile | Performance | Accessibility | Best practices | FCP | LCP | TBT | CLS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Desktop | **69** | **95** | **96** | 2.0 s | 3.2 s | 130 ms | 0 |
| Mobile | **89** | **95** | **96** | 2.0 s | 3.4 s | 140 ms | 0 |

Scores can move slightly between runs because Lighthouse is sensitive to local CPU scheduling and browser state. The important stability signals for the current shell are zero cumulative layout shift, low blocking time, and no additional runtime dependency introduced by the visual refresh. Dev-server Lighthouse scores are not comparable because Vite transforms modules on demand; use a production build for meaningful measurements.

To reproduce the measurement locally:

```sh
cd frontend
VITE_API_URL=https://api.example.com/api/v1 \
VITE_WS_URL=wss://api.example.com/api/v1/ws \
npm run build
npm run preview -- --host 0.0.0.0 --port 4173

npx lighthouse http://127.0.0.1:4173/ \
  --only-categories=performance,accessibility,best-practices \
  --output=html
```

These numbers are a checked local baseline, not a production SLA. Real deployment performance still depends on the Vercel edge, Render cold starts, database readiness, browser hardware, and the size of authenticated data views.

## Deployment

The reference deployment uses:

- **Vercel** for the Vite frontend.
- **Render** for the FastAPI service.
- **TiDB Cloud** for the MySQL-compatible database.

High-level release flow:

1. Provision the TiDB database and store credentials securely.
2. Connect the repository to Render using [render.yaml](render.yaml).
3. Run the latest Alembic migrations and provision the first Admin account.
4. Deploy the frontend from the `frontend` directory with Node 24.x.
5. Configure the real API and WebSocket origins.
6. Generate and commit the exact CSP origins with `npm run configure:csp`.
7. Verify `/health`, `/api/v1/ready`, sign-in, role navigation, SPA fallback, and realtime status.

Read the complete provider-specific procedure in [docs/deploy.md](docs/deploy.md). A Git push or a successful local build does not, by itself, establish a live production deployment.

## Security model

AF Booking is designed to fail closed around identity and sensitive operations:

- Admin-created accounts; no self-registration.
- Argon2 password hashing and HS256 JWT sessions.
- One active session per user with immediate same-process invalidation.
- Role enforcement on the backend for Agent, QC, and Admin workflows.
- Bounded request bodies, query deadlines, WebSocket message sizes, send timeouts, and rate limits.
- Exact-origin CORS and CSP configuration for hosted deployments.
- No `v-html`; user notes and booking text are rendered as plain text.
- Audit coverage for authentication, administration, notes, statuses, exports, deletion, and restoration.
- Spreadsheet formula-injection safeguards for generated exports.

See [docs/security-report.md](docs/security-report.md) for threat boundaries, storage trade-offs, and verification details.

## Operational boundaries

The following constraints are intentional and should remain visible when extending the system:

- Keep one backend instance and one worker until shared coordination is introduced.
- Do not treat performance targets as measured production guarantees.
- Do not add external notification providers without a clear delivery, retry, and audit design.
- Do not bypass generated API contracts or edit `frontend/src/types/api.generated.ts` manually.
- Do not commit credentials, provider URLs containing secrets, or local `.env` files.
- Apply migrations explicitly before starting a version that depends on them.

## Documentation map

| Topic | Guide |
| --- | --- |
| API request/response contracts | [docs/api-contract.md](docs/api-contract.md) |
| Authentication and account provisioning | [docs/auth.md](docs/auth.md) |
| Booking lookup, notes and saves | [docs/bookings.md](docs/bookings.md) |
| Home, Summary and detail workflow | [docs/booking-workspace.md](docs/booking-workspace.md) |
| Smart search and supplier folders | [docs/smart-search.md](docs/smart-search.md) |
| Realtime protocol and locks | [docs/ws-protocol.md](docs/ws-protocol.md) |
| Tasks and reminders | [docs/tasks.md](docs/tasks.md) |
| Admin, QC and Profile | [docs/admin-qc-profile.md](docs/admin-qc-profile.md) |
| Invoice management | [docs/invoices.md](docs/invoices.md) |
| Deployment | [docs/deploy.md](docs/deploy.md) |
| Database pool sizing, query diagnostics, and keyset migration | [docs/database-operations.md](docs/database-operations.md) |
| Testing and browser verification | [docs/testing.md](docs/testing.md) |
| Observability and retention | [docs/observability.md](docs/observability.md) |
| Backup and recovery | [docs/backup.md](docs/backup.md) |
| Current implementation boundaries | [PROJECT_STATE.md](PROJECT_STATE.md) |

## Project status

AF Booking is an actively developed internal application. The core booking workspace, collaboration, tasks, administration, reporting, invoices, security hardening, realtime transport, and operational tooling are implemented in the repository.

Hosted resources, provider credentials, production origins, optional Sentry/VAPID settings, and scheduled backup secrets remain operator configuration. Review [PROJECT_STATE.md](PROJECT_STATE.md) before planning new work; it records what is implemented, what remains intentionally out of scope, and which deployment assumptions are still required.

---

<p align="center">
  Built for teams that need every booking update to be clear, accountable, and easy to act on.
</p>
