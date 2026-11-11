import { describe, expect, it } from 'vitest'
import { emptyNoteSearchFilters, noteSearchKey, noteSearchQuery, noteSearchValidation, readNoteSearchQuery } from './noteSearchFilters'

describe('note search links and date limits', () => {
  it('normalizes bookmark filters and rejects ambiguous or invalid page values', () => {
    const { filters, page } = readNoteSearchQuery({ q: ' contract ', agent_id: ' 4 ', status_code: ['Done', 'New'], page: '2' })
    expect(noteSearchQuery(filters, page)).toEqual({ q: 'contract', agent_id: '4', page: '2' })
    expect(noteSearchKey(filters)).toBe(noteSearchKey({ ...filters, q: 'contract' }))
    for (const value of ['-1', '0', '1.5', 'NaN', '100001']) expect(readNoteSearchQuery({ page: value }).page).toBe(1)
  })
  it('allows 180 inclusive days and applies the business date to an open end', () => {
    const filters = { ...emptyNoteSearchFilters(), q: 'contract', date_from: '2026-01-01', date_to: '2026-06-29' }
    expect(noteSearchValidation(filters)).toBeNull()
    expect(noteSearchValidation({ ...filters, date_to: '2026-06-30' })).toBe('dateRange')
    expect(noteSearchValidation({ ...filters, date_to: '' }, '2026-06-30')).toBe('dateRange')
    expect(noteSearchValidation({ ...filters, date_to: '2025-12-31' })).toBe('dateOrder')
    expect(noteSearchValidation({ ...filters, date_from: '2026-02-30' })).toBe('dateInvalid')
  })
  it('validates keywords and IDs before issuing an API request', () => {
    const filters = { ...emptyNoteSearchFilters(), q: 'contract' }
    expect(noteSearchValidation({ ...filters, q: 'ab' })).toBe('keywordShort')
    expect(noteSearchValidation({ ...filters, q: 'a'.repeat(101) })).toBe('keywordLong')
    for (const agent_id of ['0', '-2', '1.2', '9007199254740992']) expect(noteSearchValidation({ ...filters, agent_id })).toBe('agentInvalid')
  })
})
