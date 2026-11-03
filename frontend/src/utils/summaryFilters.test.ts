import { expect, it } from 'vitest'
import {
  emptyFilters,
  readSummaryQuery,
  summaryParams,
  summaryQuery,
  summaryReturn,
  summaryValidation,
  zonedDayBoundary,
  zonedToday,
} from './summaryFilters'
it('round-trips all filters and normalizes full/partial booking searches', () => {
  const filters = {
    ...emptyFilters(),
    q: 'cw 2154654 - rdu - 2609',
    station_code: 'RDU',
    supplier_type: 'hotel',
    period: '2026-09',
    agent_id: '3',
    status_code: 'BUNDLE',
    stale: 'true',
    is_done: 'false',
    supplier: 'Example',
    date_from: '2026-11-01',
    date_to: '2026-11-03',
  }
  expect(readSummaryQuery(summaryQuery(filters, 2))).toEqual({
    filters,
    page: 2,
  })
  expect(summaryParams(filters, 2, 'UTC')).toMatchObject({
    q: 'CW2154654-RDU-2609',
    period: '2609',
    agent_id: '3',
    page: 2,
    size: 20,
    is_done: false,
    stale: true,
  })
  expect(summaryParams({ ...emptyFilters(), q: 'CW 2154654-2609' }, 1, 'UTC')).toMatchObject({
    cw_number: 'CW2154654',
    period: '2609',
  })
  expect(summaryParams({ ...emptyFilters(), q: 'CW 2154654-2609' }, 1, 'UTC')).not.toHaveProperty(
    'q',
  )
})
it('validates date/period conflicts and rejects malformed query values/return targets', () => {
  expect(
    summaryValidation({
      ...emptyFilters(),
      q: 'CW2154654-2609',
      period: '2026-10',
    }),
  ).toBe('bookingUi.periodConflict')
  expect(
    summaryValidation({
      ...emptyFilters(),
      date_from: '2026-11-03',
      date_to: '2026-11-01',
    }),
  ).toBe('bookingUi.invalidDates')
  const { filters, page } = readSummaryQuery({
    page: '-999',
    agent_id: 'no',
    station_code: 'YY',
    date_from: '2026-02-30',
    period: '2026-99',
    supplier_type: 'bad',
  })
  expect(page).toBe(1)
  expect(filters).toEqual(emptyFilters())
  expect(summaryReturn('//outside.example')).toBe('/summary')
  expect(summaryReturn('/summary?agent_id=3')).toBe('/summary?agent_id=3')
})
it('converts date filters in the user zone, including 23/25-hour DST days', () => {
  expect(zonedDayBoundary('2026-03-08', 'America/Toronto')).toBe('2026-03-08T05:00:00.000Z')
  expect(zonedDayBoundary('2026-03-08', 'America/Toronto', true)).toBe('2026-03-09T03:59:59.999Z')
  expect(zonedDayBoundary('2026-11-01', 'America/Toronto', true)).toBe('2026-11-02T04:59:59.999Z')
  expect(zonedToday('Asia/Ho_Chi_Minh', new Date('2026-11-03T20:00:00Z'))).toBe('2026-11-04')
})
