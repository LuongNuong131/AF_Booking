import type { WebSocketServerFrame } from '../types/api.generated'
import { parseBookingKey } from '../utils/bookingKey'

const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value)
const string = (value: unknown): value is string => typeof value === 'string'
const id = (value: unknown): boolean => Number.isSafeInteger(value) && Number(value) > 0
const timestamp = (value: unknown): boolean =>
  string(value) && Number.isFinite(Date.parse(value))
function key(data: Record<string, unknown>): boolean {
  if (!string(data.booking_key) || !string(data.display_key)) return false
  const parsed = parseBookingKey(data.booking_key)
  return !!parsed && 'key' in parsed && parsed.key === data.booking_key
}
function holder(data: Record<string, unknown>): boolean {
  return key(data) && id(data.user_id) && string(data.user_name)
}
const notificationTypes = new Set([
  'taken_over',
  'stale',
  'task_due',
  'watch_update',
  'assigned',
  'assignment_done',
  'work_task_created',
  'work_task_handled',
])

export function parseServerFrame(raw: unknown): WebSocketServerFrame | null {
  if (!record(raw) || !string(raw.event) || !record(raw.data)) return null
  const d = raw.data
  let valid = false
  switch (raw.event) {
    case 'ping':
    case 'pong':
      valid = true
      break
    case 'session.force_logout':
      valid = string(d.reason) && string(d.message)
      break
    case 'lock.snapshot':
      valid =
        Array.isArray(d.locks) &&
        d.locks.every((l: unknown) => record(l) && holder(l) && timestamp(l.expires_at))
      break
    case 'lock.acquired':
    case 'lock.released':
    case 'lock.denied':
      valid = holder(d)
      break
    case 'booking.updated':
      valid =
        key(d) &&
        string(d.cw_number) &&
        string(d.station_code) &&
        id(d.version) &&
        ((d.last_agent_id === null && d.last_agent_name === null) ||
          (id(d.last_agent_id) && string(d.last_agent_name))) &&
        (d.status_code === null || string(d.status_code)) &&
        (d.position === null || string(d.position)) &&
        (d.snapshot_rebuilt === undefined || typeof d.snapshot_rebuilt === 'boolean') &&
        (d.invoice_state === undefined ||
          ['unknown', 'has_invoice', 'no_invoice'].includes(String(d.invoice_state))) &&
        (d.invoice_count === undefined ||
          (Number.isSafeInteger(d.invoice_count) && Number(d.invoice_count) >= 0)) &&
        (d.change_kind === undefined || ['note', 'invoice'].includes(String(d.change_kind))) &&
        timestamp(d.updated_at) &&
        typeof d.is_done === 'boolean'
      break
    case 'system.health':
      valid = typeof d.degraded === 'boolean'
      break
    case 'catalog.updated':
      valid =
        ['users', 'statuses'].includes(String(d.resource)) &&
        typeof d.snapshots_changed === 'boolean'
      break
    case 'task.due':
      valid =
        record(d.task) &&
        key(d.task) &&
        id(d.task.id) &&
        string(d.task.message) &&
        timestamp(d.task.remind_at) &&
        timestamp(d.task.created_at) &&
        d.task.status === 'pending' &&
        d.task.is_due === true &&
        typeof d.task.is_overdue === 'boolean' &&
        typeof d.task.booking_changed_since === 'boolean' &&
        Number.isSafeInteger(d.task.snooze_count) &&
        Number(d.task.snooze_count) >= 0 &&
        d.task.completed_at === null &&
        record(d.task.booking) &&
        timestamp(d.task.booking.updated_at) &&
        typeof d.task.booking.is_done === 'boolean' &&
        (d.task.booking.last_agent === null ||
          (record(d.task.booking.last_agent) &&
            id(d.task.booking.last_agent.id) &&
            string(d.task.booking.last_agent.full_name))) &&
        (d.task.booking.last_status === null ||
          (record(d.task.booking.last_status) &&
            string(d.task.booking.last_status.code) &&
            string(d.task.booking.last_status.label))) &&
        id(d.notification_id) &&
        timestamp(d.created_at)
      break
    case 'notification.new':
      valid =
        key(d) &&
        id(d.id) &&
        (d.by_agent_name === null || string(d.by_agent_name)) &&
        timestamp(d.created_at) &&
        string(d.type) &&
        notificationTypes.has(d.type) &&
        (d.merged_count === undefined ||
          (Number.isInteger(d.merged_count) &&
            Number(d.merged_count) >= 1 &&
            Number(d.merged_count) <= 65535))
      break
  }
  return valid ? (raw as unknown as WebSocketServerFrame) : null
}
