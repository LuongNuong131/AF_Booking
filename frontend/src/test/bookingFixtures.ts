import type {
  BookingItem,
  BookingLookup,
  BookingUpdatedData,
  Note,
  NoteSaveResponse,
  PublicUser,
  Status,
} from '../types/api.generated'
export const KEY = 'CW2154654-RDU-2609'
export const user: PublicUser = {
  id: 3,
  username: 'agent',
  full_name: 'Agent',
  role: 'agent',
  is_active: true,
  settings: { timezone: 'America/Toronto' },
}
export const statuses: Status[] = [
  {
    id: 1,
    code: 'DONE',
    label: 'Done',
    position_label: 'Complete',
    note_required: false,
    is_done: true,
    sort_order: 10,
    suggest_task: false,
    default_task_days: null,
    invoice_required: true,
  },
  {
    id: 2,
    code: 'REJECTION',
    label: 'Rejection',
    position_label: 'Review',
    note_required: true,
    is_done: false,
    sort_order: 20,
    suggest_task: false,
    default_task_days: null,
    invoice_required: false,
  },
  {
    id: 4,
    code: 'BUNDLE',
    label: 'Bundle',
    position_label: 'Processing',
    note_required: false,
    is_done: false,
    sort_order: 40,
    suggest_task: false,
    default_task_days: null,
    invoice_required: false,
  },
]
export function item(version = 1): BookingItem {
  return {
    booking_key: KEY,
    display_key: 'CW 2154654-RDU-2609',
    cw_number: 'CW2154654',
    station_code: 'RDU',
    period: '2609',
    period_label: 'Sep 2026',
    supplier: { name: 'Example Hotel', type: 'hotel' },
    supplier_name: 'Example Hotel',
    supplier_type: 'hotel',
    version,
    last_status: { code: 'BUNDLE', label: 'Bundle' },
    last_position: 'Processing',
    last_agent: { id: 3, full_name: 'Agent' },
    last_note_preview: 'Original update',
    is_done: false,
    done_at: null,
    updated_at: '2026-11-03T08:00:00.000Z',
    is_stale: false,
    invoice_state: 'unknown',
    invoice_count: 0,
    invoices_preview: [],
  }
}
export function note(version = 1): Note {
  return {
    id: version,
    agent: { id: 3, full_name: 'Agent' },
    status: { code: 'BUNDLE', label: 'Bundle' },
    position: 'Processing',
    note: `Update ${version}`,
    created_at: `2026-11-03T08:00:0${version}.000Z`,
    attachments: [],
    invoice_change: null,
  }
}
export function lookup(version = 1): BookingLookup {
  return {
    booking_key: KEY,
    display_key: 'CW 2154654-RDU-2609',
    exists: true,
    version,
    resolution: {
      status: 'exact',
      input_kind: 'full',
      key: KEY,
      display_key: 'CW 2154654-RDU-2609',
    },
    snapshot: item(version),
    group: {
      cw_number: 'CW2154654',
      station_code: 'RDU',
      supplier_name: 'Example Hotel',
      supplier_type: 'hotel',
    },
    group_exists: true,
    history: { items: [note(version)], next_cursor: null },
  }
}
export function saved(version = 2): NoteSaveResponse {
  return { snapshot: item(version), note: note(version) }
}
export function event(version = 2, agentId = 5): BookingUpdatedData {
  return {
    booking_key: KEY,
    display_key: 'CW 2154654-RDU-2609',
    cw_number: 'CW2154654',
    station_code: 'RDU',
    version,
    last_agent_id: agentId,
    last_agent_name: agentId === 3 ? 'Agent' : 'Other',
    status_code: 'BUNDLE',
    position: 'Processing',
    updated_at: `2026-11-03T08:00:0${version}.000Z`,
    is_done: false,
  }
}
