# WebSocket protocol — Prompt 5

Implemented at `WS /api/v1/ws?token=<access_token>`. Production uses `wss://` directly to Render; Vercel serves the frontend. HTTP contracts stay in [api-contract.md](api-contract.md). Wire models are `backend/app/schemas/realtime.py`; generated `WebSocketClientFrame` / `WebSocketServerFrame` types are in `frontend/src/types/api.generated.ts`.

## Connection and frame envelope

Every frame is a JSON **text** message:

```json
{"event":"lock.acquire","data":{"booking_key":"CW2154654-RDU-2609"}}
```

The supplied prompts fixed event names but left the outer envelope implicit; `{event,data}` is the explicit Prompt 5 contract. Unknown fields/events and malformed frames close with 4400. Client commands send the canonical `booking_key` only. Every server payload containing `booking_key` also includes `display_key`, such as `CW 2154654-RDU-2609`. Server timestamps use UTC ISO 8601 milliseconds (`...Z`).

The JWT has the same signature/issuer/audience/expiry/SID requirements as REST. Handshake checks a fresh user row (active + matching current SID), serialized with login/revocation via the auth user lock. A stale principal cache cannot register a superseded SID. Invalid credentials close with 4401. To deliver the actual close code over a real WebSocket transport, rejection briefly accepts the upgrade and immediately closes, without registering a connection or sending a snapshot. **Ready means receipt of `lock.snapshot`, not the browser `open` event alone.**

One connection is active per user. Reconnecting with the same SID replaces the old socket (4409); the old socket's cleanup cannot remove the new connection or its lease. A new login SID sends `session.force_logout` to the previous SID and closes it. Inbound commands and scheduled pings recheck expiry/session, using the existing 12-second REST principal cache for ordinary checks. Auth helpers revoke the matching socket immediately after commit. Out-of-band DB changes remain bounded by cache expiry and the next heartbeat/command.

Uvicorn logs WebSocket handshakes even with `--no-access-log`. Application startup installs a filter on `uvicorn.error` and `uvicorn.access` that strips handshake query strings, including encoded parameter names. Application logs contain user IDs/error classes, not tokens, SIDs, frame bodies or notes. Never persist token URLs or include them in frontend diagnostics/analytics.

## Server → client

| Event | `data` | Delivery |
| --- | --- | --- |
| `booking.updated` | `{booking_key,display_key,cw_number,station_code,version,last_agent_id,last_agent_name,status_code,position,updated_at,is_done}` | All connected users, after commit |
| `lock.acquired` | `{booking_key,display_key,user_id,user_name}` | All users; repeats for a continuous same-user acquire |
| `lock.released` | `{booking_key,display_key,user_id,user_name}` | All users when a lease ends |
| `lock.denied` | `{booking_key,display_key,user_id,user_name}`; these identify the current holder | Requesting user only |
| `lock.snapshot` | `{locks:[{booking_key,display_key,user_id,user_name,expires_at}]}` | First frame after registration; replaces the client's lock map |
| `notification.new` | `{id,booking_key,display_key,by_agent_name,created_at,type}` | Notification owner only |
| `session.force_logout` | `{reason,message}` | Previous/revoked SID only, followed by close 4401 |
| `task.due` | `{task:Task,notification_id,created_at}` | Task owner only, after notification/marker commit |
| `ping` | `{}` | Application heartbeat every 25 s |
| `pong` | `{}` | Reply to a client application `ping` |

`notification.new.type` uses the existing six notification types. Implemented jobs emit `taken_over`, `stale` and `task_due`. `by_agent_name` is null for a system stale reminder. The notification row already exists before publication. The notification's owner is never selected from an inbound client field.

Force-logout reasons include `new_login`, `logout`, `password_changed`, `admin_kick`, `user_disabled`, `session_replaced`, `session_revoked`, and `token_expired`. New-login/replaced-session copy is exactly `Your account was signed in on another device.`; other reasons use `Your session has ended. Please sign in again.` No SID/token is exposed in the event.

`task.due` is implemented by Prompt 7B alongside the missing Prompt 5B API prerequisite. Its `task` field is the complete shared Task DTO (including display_key and booking summary), with `is_due:true` and pending status. `notification_id` links the accompanying private `notification.new`; `created_at` is UTC. Deduplicate by task ID/deadline and notification ID respectively. The startup/30-second job commits `notified_at` and a `task_due` notification before dispatch. On login/reopen/reconnect call GET /tasks/due once for a durable catch-up view; see [tasks.md](tasks.md).

## Client → server

| Event | `data` | Effect |
| --- | --- | --- |
| `lock.acquire` | `{booking_key}` | Acquire/refresh a canonical full-key lease; may target an unsaved booking |
| `lock.heartbeat` | `{booking_key}` | Extend the caller's current lease by 150 s; suggested client interval 30 s |
| `lock.release` | `{booking_key}` | Release only the caller's lease |
| `pong` | `{}` | Acknowledge server heartbeat |
| `ping` | `{}` | Client heartbeat; server replies `pong` |

Both `event` and lock-command `data` are required; heartbeat `data` defaults to `{}` when omitted. Partial/display keys cannot acquire a lease. Another user's release is ignored. A heartbeat without an owned lease does not create a lease; if another user holds it, the caller receives `lock.denied`.

ASGI/browser WebSocket APIs do not expose native protocol ping/pong consistently to application code. The 25 s/60 s contract therefore uses these JSON application heartbeats; native transport ping/pong may also exist, but do not replace the JSON `pong`. Lock heartbeat and JSON transport heartbeat have separate purposes. No JSON ping/pong received for 60 s closes with 4408 even if lock messages are arriving.

Example heartbeat handling (documentation only; frontend screens remain for their prompt):

```javascript
socket.onmessage = ({ data }) => {
  const frame = JSON.parse(data)
  if (frame.event === 'ping') {
    socket.send(JSON.stringify({ event: 'pong', data: {} }))
    return
  }
  // Handle the documented domain event / initial lock snapshot.
}
```

## Advisory lease semantics

`LockManager` mutates state synchronously in one event loop: one canonical key → holder/expiry, and one user → at most one key. Acquiring another key first releases the user's previous lease, including when the new target is denied. Acquiring the same key as its holder extends it without an intervening release. Same-SID socket replacement transfers the lease generation so delayed old cleanup cannot release the replacement's lease.

Expiry uses a monotonic deadline of 150 s; snapshots include a UTC `expires_at` hint. Acquire/heartbeat/snapshot remove expired leases eagerly, and a scheduler job sweeps every 25 s (within the requested 20–30 s range). Release occurs on explicit release, the holder's successful note save/replay, true disconnect, revocation, expiry, or replacement by a new SID. A different user's successful note does not steal/release the existing holder's lease. **Locks never block note writes**; database row locks and `expected_version` control writes.

All connection, queue and lock state is in memory and clears on restart. Run **one instance and one Uvicorn worker**. Multiple instances need Redis/shared ownership and pub/sub before scaling (Prompt 12.5).

## Delivery, deadlines and reconnect

Every connection has one FIFO writer and a bounded queue (128 frames). Broadcast enqueues independently and returns without awaiting network sends. Every send/close has `asyncio.timeout(WS_SEND_TIMEOUT_SECONDS)` (default 5 s). A timed-out writer or full queue retires its socket; one slow client does not hold up other recipients. Revocation drops queued domain updates to prioritize `session.force_logout` and close; delivery to an unresponsive client remains best-effort.

Note commit callback runs in this order: invalidate snapshot → update KeyIndex → release the saver’s lease → schedule owned post-commit broadcast/private notification. Event payloads are validated before commit. Dispatch is owned by the manager, so cancellation of the already committed HTTP request does not cancel publication. An idempotent UUID retry returns the original note response and never broadcasts another booking update or creates another takeover notification.

WebSocket events are incremental **best-effort** messages, not a durable event log. After reconnect, replace the lock map with `lock.snapshot`, reload the current booking/list and unread notifications through HTTP, then send `lock.acquire` again for the canonical booking being edited. Retry lost note HTTP responses with the same UUID/payload. Handle forced logout by discarding credentials; stop the superseded socket on 4409 instead of having two tabs continually replace each other. There is no durable replay cursor/ack in this prompt.

| Close code | Meaning |
| --- | --- |
| 1000 / 1001 | Normal close / server shutdown |
| 1003 | Binary messages unsupported |
| 1009 | Message exceeds configured byte limit |
| 1011 | Internal socket/heartbeat failure |
| 1013 | Authentication backend temporarily unavailable; reconnect later |
| 4400 | Invalid JSON, command or canonical booking key |
| 4401 | Invalid/replaced/expired/revoked session |
| 4408 | Missing JSON heartbeat, slow send or full outbound queue |
| 4409 | Another socket with the same user/SID superseded this connection |

## Scheduler and stale reminders

`services/scheduler.py` runs each named job in its own asyncio task with a deadline, no overlapping executions of the same job, safe error-class logging and cancellation on shutdown. Jobs run immediately at startup (catch-up), then at their interval. A failure/timeout in one job leaves other jobs running. Add future task jobs with `scheduler.add_job(name, callback, interval=..., timeout=...)`.

The stale job defaults to every 1,200 s (20 minutes, within the requested 15–30 minutes). It uses the same status-specific threshold/default 24 h as read-time stale detection, excludes Done/no-last-agent bookings, and selects unmarked rows or markers older than `updated_at`. A pessimistic transaction creates `stale` notifications and marks those rows once per episode. Marker updates explicitly preserve `updated_at` despite MySQL's automatic timestamp, and do not alter version/last agent. Concurrent scans serialize on booking rows. Note saves clear the marker for a new episode. Processing uses batches of 100.

Notification publication occurs after each batch commits. If the service slept or a socket was offline, the persisted notification is recoverable through HTTP. Read-time stale lists/flags remain authoritative while the scheduler is asleep or disabled.

| Setting | Default |
| --- | --- |
| `WS_SEND_TIMEOUT_SECONDS` | 5 |
| `WS_PING_INTERVAL_SECONDS` / `WS_IDLE_TIMEOUT_SECONDS` | 25 / 60 |
| `WS_QUEUE_SIZE` / `WS_MAX_MESSAGE_BYTES` | 128 / 4096 |
| `LOCK_TTL_SECONDS` / `LOCK_SWEEP_INTERVAL_SECONDS` | 150 / 25 |
| `SCHEDULER_ENABLED` | true |
| `TASK_JOB_INTERVAL_SECONDS` | 30 |
| `SCHEDULER_JOB_TIMEOUT_SECONDS` | 120 |
| `STALE_JOB_INTERVAL_SECONDS` / `STALE_JOB_BATCH_SIZE` | 1200 / 100 |

## Verification

From `backend`:

```sh
.venv/bin/python -m pytest tests/test_realtime.py -q
.venv/bin/python tests/run_schema_checks.py --engine mysql --suite realtime --report /tmp/realtime-mysql.xml
.venv/bin/python tests/run_schema_checks.py --engine tidb --suite realtime --report /tmp/realtime-tidb.xml
```

The database suites open **real Uvicorn/WebSocket connections** on a test-only loopback port and use verified-TLS disposable DBs. They cover two-user post-commit updates/fresh lookup, private takeover/stale notifications, nonblocking locks, expiry/heartbeat/disconnect, same-SID replacement, new-login/kick/logout/disable, actual 4401 handshake close, fresh-row handshake validation, application ping/pong, malformed/binary/oversize frames, idempotent publication, stale batching/custom thresholds/old markers and startup catch-up. Unit tests exercise a hung sender, bounded queue eviction, SID-targeted revocation, scheduler isolation and token redaction (including encoded parameter names).

## Prompt 8 / 8B extensions

Moderation may emit a `booking.updated` snapshot with null `last_agent_id`,
`last_agent_name`, `status_code` and `position` when no live notes remain. It adds
`snapshot_rebuilt:true` for delete/restore; ordinary note events include false.
This explicit nullable-field/flag extension is reflected in generated types and the
client frame validator. Clear old snapshot fields and show review even for the same
author. Invoices are retained. Snapshots/indexes are refreshed before publication.

`catalog.updated` is a new server event with
`{resource:'users'|'statuses',snapshots_changed:boolean}`. Status changes invalidate
catalogues and current booking snapshots; user display-name changes invalidate rendered
identities. The payload carries no settings, passwords, token or SID. Authentication
and all other event names remain unchanged. Additional logout reasons include
`password_reset` and `admin_role_changed`.

Booking broadcasts are coalesced for 100 ms per canonical key, retaining the highest
version. Notifications and lock/session events are delivered separately and may arrive
before that booking frame. Do not assume cross-event ordering. Private notifications
are not dropped by booking coalescing. Client booking rendering batches frames using
requestAnimationFrame and ignores an older/equal version. HTTP snapshots/histories are
authoritative; after reconnect use catch-up reads and resume the durable note outbox.


Prompt 8C integrity repair reuses booking.updated with snapshot_rebuilt:true after
commit; a no-op repair emits nothing. It preserves operational updated_at but raises
version, so clients must compare versions rather than assuming time always advances.
MAX(non-deleted note id) now determines the final snapshot after moderation/repair.
No integrity-specific socket event is added; its Admin progress page uses bounded
progress-only reads while a run is active.


## Collaboration — Prompt 8D

After a committed note, booking.updated still broadcasts once with the existing
payload. Private notification.new now supports the previously reserved watch_update,
assigned and assignment_done types. Its payload adds merged_count: positive integer,
default 1, maximum 65,535. Other notification senders retain the default. The client
accepts older frames without the additive count.

An unread watch_update keeps the same notification ID across notes; the latest frame
carries updated author/time/count. Clients must refresh its content even for a known
ID and must not increase the unread badge for that merge. A read notification is no
longer a merge target. A previous-agent watcher receives taken_over alone for the
current note. Assignment lifecycle messages are distinct from watch/takeover notices.
Recipients who are offline read their persisted notices when they reconnect; the
manager only enqueues frames to registered connections. Broadcast coalescing never
merges private notification frames. HTTP history remains authoritative.

No new client/server event name is needed. Assignment counts catch up through private
notices, personal committed notes and reconnect/visibility reads; no polling is added.
See [collaboration.md](collaboration.md) for transaction/ownership and API details.


## Operations — Prompt 8E

An explicit additive server event is now supported:

| Event | Audience | Data |
| --- | --- | --- |
| `system.health` | Admin connections only | `{degraded:boolean}` |

Admin receives this after the initial lock.snapshot and on a sampled degradation
transition (global p95 >500 ms for five minutes, or recovery). No query/request/user
statistics or SQL fingerprints are broadcast. Other roles receive no health frame.
Generated unions and client validation include this event; existing event names and
booking/notification payloads stay unchanged. The visible System page reads full
health metrics every15 seconds only while visible; the dot needs no background HTTP
polling. Metrics remain single-instance and reset on restart.

Private notification.new remains the persisted notification source. Offline
notifications of type task_due, assigned or watch_update may additionally enqueue a
minimal Web Push after commit. A connected WebSocket suppresses push, with a second
check by the worker. This adds no client WebSocket command or note-content payload.
See operations-pwa.md for VAPID, session ownership, failure and sleeping-server limits.
