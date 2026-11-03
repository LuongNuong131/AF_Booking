import { lookup } from './bookingFixtures'
import type {
  FolderCard,
  FolderDetail,
  MonthRow,
  SearchFolder,
  BookingUpdatedData,
} from '../types/api.generated'
export const CW = 'CW2154927',
  FKEY = CW + '-YUL-2609'
export function folder(): FolderCard {
  return {
    cw_number: CW,
    supplier_name: 'Hotellus Montreal Inc. d/b/a DOUBLE TREE by HILTON - YUL',
    supplier_type: 'hotel',
    station_code: 'YUL',
    booking_count: 3,
    open_count: 2,
    stale_count: 1,
    last_activity_at: '2026-11-03T08:00:00.000Z',
    latest: {
      booking_key: FKEY,
      display_key: 'CW 2154927-YUL-2609',
      period_label: 'Sep 2026',
      status: { code: 'BUNDLE', label: 'Bundle' },
      agent: { id: 3, full_name: 'Agent' },
    },
  }
}
export function months(): MonthRow[] {
  return ['2609', '2608', '2607'].map((period, i) => ({
    booking_key: `${CW}-YUL-${period}`,
    display_key: `CW 2154927-YUL-${period}`,
    period,
    period_label: ['Sep 2026', 'Aug 2026', 'Jul 2026'][i]!,
    last_status: {
      code: i === 1 ? 'DONE' : 'BUNDLE',
      label: i === 1 ? 'Done' : 'Bundle',
    },
    last_position: 'Processing',
    last_agent: { id: 3, full_name: 'Agent' },
    is_done: i === 1,
    is_stale: i === 0,
    updated_at: '2026-11-03T08:00:00.000Z',
    invoice_state: 'unknown',
    invoice_count: 0,
  }))
}
export function folderDetail(): FolderDetail {
  return { folder: folder(), months: months() }
}
export function folderResult(): SearchFolder {
  return { kind: 'folder', query: CW, ...folderDetail() }
}
export function folderEvent(): BookingUpdatedData {
  return {
    booking_key: FKEY,
    display_key: 'CW 2154927-YUL-2609',
    cw_number: CW,
    station_code: 'YUL',
    version: 2,
    last_agent_id: 5,
    last_agent_name: 'Other',
    status_code: 'DONE',
    position: 'Complete',
    updated_at: '2026-11-03T08:00:02.000Z',
    is_done: true,
  }
}

export function folderLookup() {
  const value = lookup(),
    data = folder()
  value.booking_key = FKEY
  value.display_key = 'CW 2154927-YUL-2609'
  value.resolution = {
    status: 'exact',
    input_kind: 'full',
    key: FKEY,
    display_key: value.display_key,
  }
  value.group = {
    cw_number: CW,
    station_code: 'YUL',
    supplier_name: data.supplier_name,
    supplier_type: 'hotel',
  }
  value.snapshot = {
    ...value.snapshot!,
    booking_key: FKEY,
    display_key: value.display_key,
    cw_number: CW,
    station_code: 'YUL',
    supplier: { name: data.supplier_name, type: 'hotel' },
    supplier_name: data.supplier_name,
    supplier_type: 'hotel',
  }
  return value
}
