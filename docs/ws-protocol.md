# WebSocket contract — Prompt 1B

**Status: event names reserved; runtime not implemented.** This document fixes the direction and spelling of the events supplied by Prompt 1B. The envelope, event-specific payload fields, acknowledgement/correlation mechanism, and close codes were not supplied. Define them here in the corresponding implementation prompt before shipping; shared code currently exports event-name unions only.

## Connection

Prompt 3 supplies `SessionEvents.force_logout(user_id, old_session_id, reason)` and a no-op default implementation. Auth calls it after session revocation commits, targeting only the old session. This is an internal transport interface for `session.force_logout`, not a new wire envelope or an active WebSocket endpoint. Inject the future manager with `create_app(..., session_events=...)`; callback failure does not restore a revoked session.

- Endpoint: `WS /api/v1/ws?token=`; production uses `wss://` directly to the Render backend.
- An active authenticated session is required. A replaced session is invalid even if its token has not expired.
- The token must not appear in application logs, telemetry, or saved URLs. The WebSocket implementation must redact query tokens from handshake/access logging.
- Keep the deployment at one backend instance and one worker while connection/lock state is in process memory. Multiple instances require shared coordination before scaling.

## Server → client

| Event | Purpose |
| --- | --- |
| `booking.updated` | Small committed booking-change event; no full booking list |
| `lock.acquired` | Advisory working lock acquired |
| `lock.released` | Advisory working lock released/expired |
| `lock.snapshot` | Current advisory lock state |
| `lock.denied` | Requested advisory lock was not acquired |
| `notification.new` | A notification for the current user |
| `task.due` | A private task for the current user is due |
| `session.force_logout` | The session must end |

## Client → server

| Event | Purpose |
| --- | --- |
| `lock.acquire` | Request an advisory lock for a booking |
| `lock.heartbeat` | Refresh the client's current advisory lock |
| `lock.release` | Release the client's current advisory lock |

## Required invariants for later implementation

- Events use canonical booking keys. Any payload object with `booking_key` must also have `display_key`; never use the display key as identity.
- Events are incremental and emitted after commits; they do not replace paginated HTTP reads or the database as source of truth.
- A working lock is advisory, not a write prohibition. Its idle expiry is 150 seconds; the client heartbeat interval is 30 seconds. Release on save, navigation, or disconnect as specified by Prompt 1.
- Sends have a bounded deadline (`WS_SEND_TIMEOUT_SECONDS`, default 5). The request timeout middleware must not apply an HTTP request lifetime to a WebSocket connection.
- Reconnect/resync behavior and notification ownership must be tested when implemented; local memory and a surviving socket cannot be assumed across deployments.
- WebSocket errors and close payloads remain to be specified; do not assume the HTTP error envelope determines a WebSocket frame format.
