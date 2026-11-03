# Frontend foundation (Prompt 6)

The Vue workspace now supports real sign-in, session restoration, role-based navigation,
light/dark themes, private notifications and the Prompt 5 WebSocket protocol. Prompt 7 now implements Home,
Summary and booking detail, including lookup, history, note entry, drafts, conflict
review and live tables. See [booking-workspace.md](booking-workspace.md) for the workflow.
Reminder UI and task mutations remain subsequent work. Profile
shows the authenticated account and a local theme preference; it does not call the
reserved profile mutation API. Admin and Reports have guards and shell routes only.

## Development and build

Use Node 24 and Python 3.12. Start the configured backend using [auth.md](auth.md),
including migrations and an operator-provisioned account. There is no registration or
default password. In a second terminal:

```sh
cd frontend
npm ci
# Copy only when no local configuration already exists:
test -f .env || cp .env.example .env
npm run dev
```

Vite serves port 5173. Defaults use `http://localhost:8000/api/v1` and the matching
WebSocket endpoint. Backend CORS must allow the exact browser origin, normally
`http://localhost:5173`. Changing the API hostname/port requires changing an explicit
`VITE_WS_URL` too, or leaving it blank to derive it from the API URL.

| Variable | Meaning |
| --- | --- |
| `VITE_API_URL` | API base URL, ending in `/api/v1`; required for production |
| `VITE_WS_URL` | Optional WebSocket URL ending in `/api/v1/ws`; otherwise derived from API URL |
| `VITE_TIMEOUT_SCALE` | Positive request-timeout multiplier; default `1` |
| `VITE_API_BASE_URL` | Legacy fallback used only when `VITE_API_URL` is unset/blank |

Production requires HTTPS/WSS. URLs cannot contain credentials, query strings or
fragments. These variables are public bundle configuration, never secrets.

```sh
cd frontend
npm test
VITE_API_URL=https://YOUR-API.onrender.com/api/v1 \
VITE_WS_URL=wss://YOUR-API.onrender.com/api/v1/ws npm run build
```

The build runs strict Vue/TypeScript checking. Vercel serves `dist` with the committed
SPA fallback; WSS connects directly to Render. See [deploy.md](deploy.md).

## Structure and session handling

- `src/router`: guest/role guards, canonical booking URL redirects and lazy workspace pages.
- `src/stores`: auth, UI/theme, notifications, realtime and the due-task foundation.
- `src/runtime/application.ts`: auth-aware API hooks, WebSocket lifecycle and refresh dispatch.
- `src/api`: Axios bearer injection, sanitized errors and runtime auth/frame validation.
- `src/composables`: request deadlines, realtime transport, view refresh, route resilience and keyboard bindings.
- `src/components`, `src/layouts`, `src/views`: shared components and routed UI.
- `src/locales/en.json`: every visible message; API error codes select translations.
- `src/types/api.generated.ts`: generated from backend schemas; never edit manually.
- `src/utils`: shared booking-key aliases, zoned time formatting and storage helpers.

Tokens live in memory plus per-tab `sessionStorage`; user data is restored with
`GET /auth/me` after reload. They are not stored in `localStorage`. Logout, a current
401 or a WebSocket force-logout clears private stores and unmounts protected content.
Delayed responses from an older login cannot log out a newer session. Passwords stay
only in the editable login form and the outgoing request; normalized request errors
exclude Axios configs and bodies. Do not log WebSocket URLs, which carry a token.

`SESSION_REPLACED` uses the exact English Prompt 1B copy, “Your account was signed in
on another device.” Other session-end reasons ask the user to sign in again. A 403
shows the permission message. Backend authorization remains authoritative.

Themes default to the system setting and persist `system`, `light` or `dark` in
`localStorage`. Other tabs receive theme changes through the storage event. An early
head script applies the preference before rendering. CSS variables and Element Plus
variables cover both themes. No component uses `v-html`.

## Requests and view refresh

`src/config/timeouts.ts` is the only source of client deadlines: lookup/search 8 s,
lists 10 s, note save 15 s, task/profile 10 s, export 60 s, warm-up 45 s, slow threshold
3 s. The scale applies to those request timings; route/visibility/lease protocol
intervals remain independent. Values are bounded to positive native-timer limits.

```ts
const request = useRequest(async ({ signal, timeoutMs }, key: string) => {
  const response = await api.get('/bookings/lookup', {
    params: { key }, signal, timeout: timeoutMs,
  })
  return response.data
}, { timeoutMs: timeouts.lookup, retry: true })
```

`run` returns data on success and `undefined` on failure/cancellation; callers inspect
`state` and `error`. States are `idle`, `loading`, `slow`, `timeout`, `error`, `success`.
Bind `RequestStatus` next to the active input and bind button disablement to `pending`.
The input remains editable. Cancel/retry keeps its value and focus; no fullscreen
API overlay is used. Scope disposal cancels owned requests.

A total AbortController deadline bounds even a transport that ignores cancellation.
Axios receives the remaining deadline. Starting another request cancels its predecessor;
request generations discard late results. Timers and button state clear in `finally`.
Only explicitly enabled, proven GET network/503/504 failures retry, once, after
300–500 ms jitter and the larger `Retry-After` delay. Retry stays within the original
deadline. POST/PATCH/DELETE/PUT never auto-retry. Note outbox replay is reserved for
Prompt 8B and must retain its original request UUID.

Route loading ends after 20 seconds with a nonblocking Retry banner, including on
initial lazy-load failure. A tab hidden for at least 60 seconds emits a refresh request.
Future data pages register `useViewRefresh(load)` to reload current data after
visibility, reconnect or retry; the current notification list already subscribes.
Home, Summary and detail subscribe to refresh signals, preserving form drafts; no task API is called.
Error boundaries isolate render failures and offer a section retry.

## WebSocket and keyboard integration

`useRealtime` connects after authentication and treats `lock.snapshot` as readiness.
It answers JSON ping with pong, reconnects after 1/2/5/15 seconds, refreshes the current
view on reconnect and renews the active lease every 30 seconds. Stores accept only
validated frames, keep a bounded booking-update map, and clear locks when disconnected.
Booking workspace scopes release/acquire canonical booking locks on selection/clear/navigation. Lock denial warns without
blocking note entry. See [ws-protocol.md](ws-protocol.md) for exact frames/close codes.

A 4409 means another tab with the same SID owns the socket: stop reconnecting and
show “Connected in another tab”, retaining the valid REST session. A new login's
`session.force_logout` clears the old session and redirects to Login. The due-task
store provides a list/counter/invalidation hook; it does not call future task APIs.

Booking input/note components register `useBookingShortcuts` with input/scope
references, lookup/save/clear callbacks and the dynamic status catalogue. The shared
VueUse listener implements `/`, Enter, Ctrl/Command+Enter, Alt+1…5 by `sort_order`,
Escape and `?`. Unrelated editable fields, IME composition and Ctrl+K are left alone.
The shortcut guide is available from the sidebar/header. Booking text/copy uses the
shared key helpers and `BookingKeyText`; URLs always retain canonical keys. Dates use
`DD MMM YYYY HH:mm:ss` plus the user's `settings.timezone` offset/label, with a valid
browser zone (then UTC) as fallback.

The backend's current `notification.new`/persisted stale notification has no hours
value. The dropdown uses a separate generic English stale message instead of inventing
an elapsed duration; the supplied `notif_stale` template remains unchanged for future
payloads that can fill it. No endpoint or event contract changed in this prompt.

## Verification

Vitest covers request deadlines/cancellation/races/retries, scoped shortcuts, role and
URL guards, auth restoration, session-aware Axios errors, notification races, theme
persistence, daylight-saving time formatting, route watchdog/visibility and render
boundaries. The shared Python/TypeScript key fixture and all Prompt 1B strings remain
tested. See [testing.md](testing.md) for the real Chromium + Vue + FastAPI + TLS TiDB
flow and its CI job.
