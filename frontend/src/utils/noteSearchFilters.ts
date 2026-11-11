import type { LocationQuery } from 'vue-router'
export interface NoteSearchFilters { q: string; date_from: string; date_to: string; agent_id: string; status_code: string }
export const emptyNoteSearchFilters = (): NoteSearchFilters => ({ q: '', date_from: '', date_to: '', agent_id: '', status_code: '' })
const scalar = (value: unknown) => typeof value === 'string' ? value.trim() : ''
export function readNoteSearchQuery(query: LocationQuery) {
  const filters = Object.fromEntries(Object.keys(emptyNoteSearchFilters()).map(key => [key, scalar(query[key])])) as unknown as NoteSearchFilters
  const candidate = Number(scalar(query.page))
  return { filters, page: Number.isInteger(candidate) && candidate > 0 && candidate <= 100000 ? candidate : 1 }
}
export function noteSearchQuery(filters: NoteSearchFilters, page = 1) {
  return { ...Object.fromEntries(Object.entries(filters).map(([key, value]) => [key, value.trim()]).filter(([, value]) => value)), ...(page > 1 ? { page: String(page) } : {}) }
}
export const noteSearchKey = (filters: NoteSearchFilters) => JSON.stringify(noteSearchQuery(filters))
function dateValue(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return NaN
  const result = Date.parse(`${value}T00:00:00Z`)
  return Number.isFinite(result) && new Date(result).toISOString().slice(0, 10) === value ? result : NaN
}
export function noteSearchValidation(filters: NoteSearchFilters, today = '') {
  if (filters.q.trim().length < 3) return 'keywordShort'
  if (filters.q.trim().length > 100) return 'keywordLong'
  const start = filters.date_from ? dateValue(filters.date_from) : null
  const end = filters.date_to ? dateValue(filters.date_to) : today ? dateValue(today) : null
  if ((start !== null && !Number.isFinite(start)) || (end !== null && !Number.isFinite(end))) return 'dateInvalid'
  if (start !== null && end !== null && start > end) return 'dateOrder'
  if (start !== null && end !== null && (end - start) / 86400000 >= 180) return 'dateRange'
  if (filters.agent_id && (!/^\d+$/.test(filters.agent_id) || !Number.isSafeInteger(Number(filters.agent_id)) || Number(filters.agent_id) <= 0)) return 'agentInvalid'
  if (filters.status_code.length > 40) return 'statusInvalid'
  return null
}
