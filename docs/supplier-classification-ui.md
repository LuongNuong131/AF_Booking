# Supplier classification and interface completion

## Workflow

In Home or booking detail, open an existing booking and choose **Edit classification**
(**Sửa phân loại**). Select Hotel or Transportation and save. Agent, QC and Admin all
use the same action. It is also available on the supplier-folder screen. Imported
unclassified suppliers can be assigned either classification.

The inline form explains that classification belongs to the **CW/station folder**:
all of its monthly bookings share the new value. A folder at another station is
unaffected. Saving preserves any note draft, booking status, note history, ownership,
invoice declarations, booking version and operational update timestamp.

Saving disables the form while the request is pending. A failure keeps the selection
available for manual retry; cancelling does not write. Focus returns to the action
when the edit closes. Switching folders cancels the pending client request and
prevents a late result from updating the new folder.

Admin/QC retain the separate **Edit supplier** action for names, recurrence and
unclassified values. Agents submit a type-only patch; including other fields is
rejected atomically by the service after rechecking the active session and live role.
Every successful folder patch records actor, station and before/after values in the
existing audit log. Existing index and snapshot caches are invalidated after commit.
No migration or new dependency is required.

## Interface work

- Restricted the mobile card transformation to the interactive booking table.
  Daily reports and personal reports keep their column headings and scroll within
  their own container.
- Completed inline classification styling, ticket textarea and handling forms,
  report controls/sections, status summaries and note-search result cards.
- Added empty states for note search and filtered user, audit, status and supplier
  administration views.
- Added visible request-loading feedback and removed nonfunctional Retry buttons
  when a component has no retry handler. Reduced-motion preferences are respected.
- Used existing theme tokens, English/Vietnamese translations and responsive layout
  for desktop, tablet, mobile, light and dark themes.

## Validation

See the verification results in `quality/supplier-classification-verification.json`.
The browser runner uses the real Vue application, FastAPI and a disposable MySQL
instance; it does not intercept API responses. It checks all three roles, preservation
of drafts/history/snapshot fields, English/Vietnamese, dark mode, and 200 route/width
combinations across 320, 375, 768, 1024 and 1440 pixels.

To repeat against isolated seeded accounts named `agent`, `qc`, and `admin`:

```sh
cd frontend
BOOKING_E2E_ARTIFACTS=/absolute/path/to/artifacts \
BOOKING_E2E_PASSWORD='<test-account-password>' \
BOOKING_CHROMIUM_PATH=/usr/bin/chromium \
node e2e/classification.mjs
```

The runner creates synthetic bookings/tickets if they do not exist. Run it only
against a disposable local/test database. The password is read from the environment
and never saved in artifacts. Optional `BOOKING_E2E_URL` and `BOOKING_E2E_API` change
the local frontend/API targets; `BOOKING_E2E_ROLES` selects a comma-separated subset.

These checks do not establish production deployment, TiDB compatibility for this
release, private object-storage uploads, or all of the application's database suites.
The ordinary backend run skips suites that require their own database configuration;
the affected folder workflow is separately tested against TLS MySQL 8.4.
