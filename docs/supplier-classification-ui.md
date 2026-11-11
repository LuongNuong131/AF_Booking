# Booking classification and operational UI

See [the current administration and report-center guide](admin-report-center.md).
Classification is now an action on each booking row and workspace, with a per-booking
override. Agent, QC and Admin all have this action. Imported unclassified bookings can
be classified individually; sibling monthly bookings retain their own values.

The current browser runner is `frontend/e2e/management.mjs`;
`frontend/e2e/classification.mjs` delegates to it. It exercises real local API calls,
row/workspace classification, report downloads, responsive administration screens,
user recycle/restore/purge and Vietnamese dark mode. Run only against disposable
seeded accounts and a disposable database:

```sh
cd frontend
BOOKING_E2E_ARTIFACTS=/absolute/path/to/local/artifacts \
BOOKING_E2E_PASSWORD='<test-account-password>' \
BOOKING_CHROMIUM_PATH=/usr/bin/chromium \
node e2e/management.mjs
```

The runner creates synthetic bookings and a temporary test account. Credentials are
read from the environment. Screenshots and exported example files remain local.
