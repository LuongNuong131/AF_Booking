import type { WebSocketServerFrame } from '../types/api.generated'
import { parseBookingKey } from '../utils/bookingKey'

const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value)
const string = (value: unknown): value is string => typeof value === 'string'
const id = (value: unknown): boolean => Number.isSafeInteger(value) && Number(value) > 0
const timestamp = (value: unknown): boolean => string(value) && Number.isFinite(Date.parse(value))
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
        id(d.last_agent_id) &&
        string(d.last_agent_name) &&
        string(d.status_code) &&
        string(d.position) &&
        timestamp(d.updated_at) &&
        typeof d.is_done === 'boolean'
      break
    case 'notification.new':
      valid =
        key(d) &&
        id(d.id) &&
        (d.by_agent_name === null || string(d.by_agent_name)) &&
        timestamp(d.created_at) &&
        string(d.type) &&
        notificationTypes.has(d.type)
      break
  }
  return valid ? (raw as unknown as WebSocketServerFrame) : null
}
