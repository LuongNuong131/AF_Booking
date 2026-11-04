import type { BookingItem, BookingUpdatedData } from '../types/api.generated'
export function patchBooking(
  row: BookingItem,
  event: BookingUpdatedData,
  statuses: { code: string; label: string }[],
): BookingItem {
  if (event.version <= row.version) return row
  return {
    ...row,
    version: event.version,
    invoice_state: (event.invoice_state ?? row.invoice_state) as BookingItem['invoice_state'],
    invoice_count: event.invoice_count ?? row.invoice_count,
    last_agent:
      event.last_agent_id && event.last_agent_name
        ? { id: event.last_agent_id, full_name: event.last_agent_name }
        : null,
    last_status: event.status_code
      ? {
          code: event.status_code,
          label: statuses.find((s) => s.code === event.status_code)?.label ?? event.status_code,
        }
      : null,
    last_position: event.position,
    updated_at: event.updated_at,
    is_done: event.is_done,
    done_at:
      event.change_kind === 'invoice' ? row.done_at : event.is_done ? event.updated_at : null,
    is_stale: event.is_done ? false : row.is_stale,
    stale_hours: event.is_done ? null : row.stale_hours,
  }
}
