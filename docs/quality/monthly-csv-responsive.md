# CSV, monthly generation and responsive UI verification

The release adds reviewed CSV repairs and a 2,000-source-row limit, per-folder
monthly recurrence with clean booking records, AF branding, and responsive layouts.
No operator CSV or production credentials are included in this repository.

## Validation

- Backend unit run: 201 passed, 168 integration tests skipped without a disposable
  database URL. Database checks below were run separately against verified TLS TiDB.
- Frontend unit run: 54 files, 250 tests passed.
- Backend Ruff lint/format and generated contract parity passed; frontend ESLint,
  security checks and production Vite build passed.
- TiDB booking suite with both supplied datasets: 32 passed. The proposed full-file
  policy (`station_source=station_code`, missing supplier fill enabled) parsed 1,425
  source rows into 1,400 unique bookings, 35 duplicate expanded rows and 14 reported
  adjustments. Applying in the disposable database succeeded; applying again added
  zero bookings. This policy still requires the operator to review source repairs.
- TiDB migration/schema validation passed through revision 0013.
- Monthly integration checks rerun after choosing the latest eligible booking as
  the initial recurrence baseline: 2 passed. They cover the Vietnam day-25 boundary,
  metadata inheritance, clean status/note/invoice state, preserved older history,
  sparse historic periods, repeat execution, paused folders and protected triggers.
- Chromium with the real Vue frontend, API, WebSocket and disposable TLS database:
  workspace, folder navigation/editing and Admin workflows passed. The folder
  browser assertions were updated for three supplier classifications and CW/station
  routes introduced by the previous release.

The responsive browser check passed. Its script visits 13 routes at widths 320, 375, 768, 1024 and
1440, checks document overflow after API requests settle, checks a mobile dialog,
English/Vietnamese and dark mode, then previews the full CSV and all 14 adjustments.
This checks browser viewport behavior; it does not represent physical Safari/iOS
or Android device certification.

## Operational boundaries

Production imports require the operator's authenticated Admin session. No production
booking data was written during these checks. The monthly GitHub Actions trigger
requires the API URL repository variable and a shared Render/Actions token; adding
the workflow alone does not configure provider secrets. See
[the deployment and import guide](../monthly-bookings-vi.md).
