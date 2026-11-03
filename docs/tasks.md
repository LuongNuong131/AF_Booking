# Reminder tasks — Prompt 7B

Home now has My bookings / Task tabs, ten-row Pending/Completed pages and task actions.
Task buttons appear beside Save, on My bookings rows, Summary rows and booking cards.
Alt+T opens the current booking's dialog; Enter submits and Escape closes it. After a
successful note save, quick reminder chips appear for ten seconds without blocking
the note form. `suggest_task` statuses receive a stronger highlight.

The repository did not yet contain the assumed Prompt 5B APIs. This change implements
those task/profile endpoints and the due scheduler alongside the UI. All existing
paths, snake_case fields and error codes remain; the previously unspecified response
envelopes and `task.due` payload are recorded in [api-contract.md](api-contract.md).

## Dates and preferences

Profile saves these keys in `users.settings` through `PATCH /api/v1/profile`:

| Key | Default |
| --- | --- |
| `timezone` | Backend `BUSINESS_TIMEZONE`, normally `Asia/Ho_Chi_Minh` |
| `default_remind_time` | `09:00` |
| `skip_weekends` | `true` |
| `task_sound` | `false` |
| `web_notifications` | `false` |

Public login/me responses include these defaults even when no settings were stored.
Profile changes merge only the permitted keys and preserve other existing settings.
Changing the timezone changes how an existing UTC deadline displays, not its instant.

Quick dates use the user's local calendar. With Skip Saturdays and Sundays enabled,
Tomorrow/+2/+3/+5 count working days; +1 week means five working days. With it disabled,
they count calendar days and +1 week means seven days. Holidays are not excluded.
Manual date inputs always accept calendar dates. The dialog shows a weekday, full
date/time and timezone confirmation using the shared date formatter.

Create/reschedule requires a future local time from today through 90 calendar days
ahead. Both client and server reject nonexistent times at a daylight-saving jump;
an ambiguous time at the autumn overlap uses its first occurrence (`fold=0`). Only
`remind_date` and `remind_time` are sent; the server converts them to UTC. Message-only
edits may preserve an overdue deadline. New messages are plain text, at most 255
characters; a blank message becomes `Check mail supplier...`.

## Private API and retry behavior

Every endpoint requires the current active SID. Other users' task IDs return 404.
Each user can have five pending tasks per booking; the sixth returns
`422 TASK_LIMIT_REACHED`. A user-row lock serializes creation and the limit check.

| Request | Response |
| --- | --- |
| `POST /bookings/{key}/tasks` | `Task` |
| `GET /bookings/{key}/tasks` | Own pending `Task[]`, at most 5 |
| `GET /tasks?view=pending\|due\|done&page=1&size=10` | `{items,total,page,size}` |
| `GET /tasks/due` | `{items,total}`; first 100 due tasks, exact total |
| `PATCH /tasks/{id}` | Updated `Task` |
| `POST /tasks/{id}/complete` | Completed `Task` |
| `POST /tasks/{id}/snooze` | Updated `Task` |
| `DELETE /tasks/{id}` | Cancelled `Task`; no hard deletion |

Paths above omit `/api/v1`. Create accepts `{remind_date,remind_time?,message?,client_request_id?}`;
the Vue client always supplies a UUID and retains it for an uncertain manual retry of
the same payload. Apply migration **0003** (`alembic upgrade head`) before starting
this version. It adds a request fingerprint and original creation result to
`booking_tasks`; a replay returns the original result even after editing/completion,
without creating another row. Reusing a UUID for another owner/payload returns 422.
Older rows with no stored result cannot be replayed using this new contract.

Edit accepts optional `remind_date`, `remind_time`, `message`; snooze uses the same
body and requires a date or time. Fields omitted on edit retain their value. Complete
and cancel are idempotent for the same terminal state. Snoozing to the same absolute
date/time does not increment `snooze_count` again. Mutations mark the task's existing
unread notifications read and write an audit record in the same transaction.

The Pinia store applies actions optimistically, prevents duplicate clicks and restores
the previous task/count/toast on failure while preserving newer booking events. It
refreshes authoritative due/page data after an action. Mutations never auto-retry;
the user can explicitly retry. Session reset cancels requests and clears private state.

## Delivery and catch-up

The shared scheduler registers `tasks.due` at startup and every
`TASK_JOB_INTERVAL_SECONDS` (default 30, configurable up to 60). It commits the task's
`notified_at` marker and private `task_due` notification together, then sends
`notification.new` and `task.due` only to that user. Processing uses batches of 100.
Snoozing to a different deadline clears the marker for a new notification episode.
Keep the existing single backend instance/worker deployment constraint.

`task.due` uses `{event:"task.due",data:{task:Task,notification_id,created_at}}`.
It creates a persistent reminder with Open booking, Done and Snooze actions; dismissing
the toast leaves the task pending. The tab title and Task badge show the due count;
the private notification contributes to the bell's unread count. Duplicate frames
and late frames for completed/cancelled or locally superseded deadlines are ignored.
`booking.updated` patches status/agent/Done/change warnings in place without fetching
the whole task list. Pending-task bells reuse `my_tasks` and `my_pending_tasks`.

Login/session restoration and authenticated WebSocket reconnect each trigger one
`GET /tasks/due`; returning after a tab was hidden for at least 60 seconds also
refreshes due tasks. A nonempty result opens the due summary. There is no polling.
HTTP due data does not depend on `notified_at`, so catch-up works after server sleep
or an offline browser. A stopped browser/server cannot display live browser alerts.

Sound is optional and plays only after a pointer/keyboard interaction has unlocked
audio. OS notifications require both the saved preference and browser permission.
Permission is requested only by the explicit enable control in Profile. This uses
the browser Notification API while the app is running; service-worker Web Push
subscription remains for Prompt 8E. Every message renders through text interpolation.

## Manual verification

1. Migrate the intended development DB to head, seed/provision an account, start the
   backend with scheduler enabled and Vue using the exact allowed CORS origin.
2. Open an existing booking. Press Alt+T, choose today and a time two minutes ahead
   in the displayed timezone, then Enter. Reopen the dialog to see the pending task.
3. Keep the app open through that time plus up to 30 seconds. Verify the persistent
   toast, bell badge, Task count and browser title. Snooze it to tomorrow; the due
   count drops. Complete a task and use Add note to open the booking and focus Note.
4. Create another reminder, close the browser and reopen after it is due. Sign in if
   needed (the token is stored per tab). The due summary lists it with Open booking.
5. Enable sound and Notification explicitly in Profile; save and reload. Check audio
   after interacting and check OS notification behavior for granted/denied permission.
6. Create five pending tasks on one booking; a sixth shows the limit message. Edit
   one, cancel another, and verify the count. Use another account to confirm privacy.

Automated commands and real Chromium coverage are in [testing.md](testing.md).
