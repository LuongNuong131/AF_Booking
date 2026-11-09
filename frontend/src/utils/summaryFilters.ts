import type { LocationQuery } from 'vue-router'
import { parseBookingKey } from './bookingKey'
export interface SummaryFilters {
  invoice_state: string
  invoice: string
  q: string
  status_code: string
  agent_id: string
  station_code: string
  supplier_type: string
  period: string
  supplier: string
  date_from: string
  date_to: string
  is_done: string
  stale: string
}
export const emptyFilters = (): SummaryFilters => ({
  invoice_state: '',
  invoice: '',
  q: '',
  status_code: '',
  agent_id: '',
  station_code: '',
  supplier_type: '',
  period: '',
  supplier: '',
  date_from: '',
  date_to: '',
  is_done: '',
  stale: '',
})
const text = (value: unknown, limit = 100) =>
  typeof value === 'string' ? value.slice(0, limit) : ''
const validDate = (value: string) =>
  /^20\d{2}-\d{2}-\d{2}$/.test(value) &&
  !Number.isNaN(Date.parse(value)) &&
  new Date(value).toISOString().slice(0, 10) === value
export function readSummaryQuery(query: LocationQuery): {
  filters: SummaryFilters
  page: number
} {
  const f = emptyFilters()
  f.invoice = text(query.invoice, 100).trim().toUpperCase()
  if (['has_invoice', 'no_invoice', 'unknown'].includes(String(query.invoice_state)))
    f.invoice_state = String(query.invoice_state)
  f.q = text(query.q)
  f.status_code = text(query.status_code, 40)
  f.supplier = text(query.supplier)
  const agent = text(query.agent_id, 16)
  if (/^[1-9]\d*$/.test(agent) && Number.isSafeInteger(Number(agent))) f.agent_id = agent
  const station = text(query.station_code, 3).toUpperCase()
  if (/^[A-Z]{3}$/.test(station)) f.station_code = station
  if (query.supplier_type === 'hotel' || query.supplier_type === 'transportation')
    f.supplier_type = query.supplier_type
  if (/^20\d{2}-(0[1-9]|1[0-2])$/.test(text(query.period))) f.period = text(query.period)
  for (const key of ['is_done', 'stale'] as const)
    if (query[key] === 'true' || query[key] === 'false') f[key] = query[key]
  for (const key of ['date_from', 'date_to'] as const)
    if (validDate(text(query[key]))) f[key] = text(query[key])
  const rawPage = Number(query.page ?? 1)
  return {
    filters: f,
    page: Number.isSafeInteger(rawPage) ? Math.min(100000, Math.max(1, rawPage)) : 1,
  }
}
export function summaryQuery(filters: SummaryFilters, page: number): Record<string, string> {
  return Object.fromEntries([
    ...Object.entries(filters)
      .filter(([, value]) => value.trim())
      .map(([key, value]) => [key, value.trim()]),
    ...(page > 1 ? [['page', String(page)]] : []),
  ])
}
export function zonedToday(timeZone: string, now = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now)
  const p = (key: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === key)!.value
  return `${p('year')}-${p('month')}-${p('day')}`
}
export function zonedDayBoundary(day: string, timeZone: string, end = false): string {
  // Solve local midnight in the user's IANA zone; next midnight handles 23/25-hour DST days.
  const date = new Date(`${day}T00:00:00.000Z`)
  if (end) date.setUTCDate(date.getUTCDate() + 1)
  const wanted = date.getTime()
  let instant = wanted
  const formatter = new Intl.DateTimeFormat('en-GB', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  })
  for (let n = 0; n < 4; n++) {
    const parts = formatter.formatToParts(new Date(instant))
    const p = (key: Intl.DateTimeFormatPartTypes) =>
      Number(parts.find((part) => part.type === key)!.value)
    const rendered = Date.UTC(
      p('year'),
      p('month') - 1,
      p('day'),
      p('hour'),
      p('minute'),
      p('second'),
    )
    const difference = wanted - rendered
    instant += difference
    if (!difference) break
  }
  return new Date(instant - (end ? 1 : 0)).toISOString()
}
export function summaryValidation(f: SummaryFilters): string | null {
  if (f.date_from && f.date_to && f.date_from > f.date_to) return 'bookingUi.invalidDates'
  const key = parseBookingKey(f.q)
  if (key && !('key' in key) && f.period && key.period !== f.period.slice(2).replace('-', ''))
    return 'bookingUi.periodConflict'
  return null
}
export function summaryParams(
  f: SummaryFilters,
  page: number,
  zone: string,
): Record<string, string | number | boolean> {
  const params: Record<string, string | number | boolean> = {
    page,
    size: 20,
    sort: 'updated_at_desc',
  }
  for (const [key, value] of Object.entries(f)) if (value.trim()) params[key] = value.trim()
  if (f.period) params.period = f.period.slice(2).replace('-', '')
  if (f.date_from) params.date_from = zonedDayBoundary(f.date_from, zone)
  if (f.date_to) params.date_to = zonedDayBoundary(f.date_to, zone, true)
  const parsed = parseBookingKey(f.q)
  if (parsed && 'key' in parsed) params.q = parsed.key
  else if (parsed) {
    delete params.q
    params.cw_number = parsed.cw_number
    params.period = parsed.period
  }
  for (const key of ['is_done', 'stale'] as const) if (f[key]) params[key] = f[key] === 'true'
  return params
}
export function summaryReturn(value: unknown): string {
  return typeof value === 'string' &&
    value.length <= 4000 &&
    !/[\\\p{Cc}\p{Cf}]/u.test(value) &&
    (value === '/summary' ||
      value.startsWith('/summary?') ||
      /^\/summary\/folders\/CW[A-Z0-9]{4,10}(?:-[A-Z]{3})?(?:\?[^#]*)?$/.test(value))
    ? value
    : '/summary'
}
