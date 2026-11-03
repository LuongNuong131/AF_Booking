import { expect, it } from 'vitest'
import {
  addBusinessDays,
  quickReminderDate,
  reminderInstant,
  validateReminder,
  reminderPreferences,
  confirmation,
} from './taskDates'
it.each([
  ['2026-11-06', 1, true, '2026-11-09'],
  ['2026-11-06', 2, true, '2026-11-10'],
  ['2026-11-06', 1, false, '2026-11-07'],
  ['2026-12-25', 5, true, '2027-01-01'],
  ['2026-11-07', 0, true, '2026-11-07'],
])('adds reminder days %s + %s', (day, n, skip, expected) => {
  expect(addBusinessDays(day as string, n as number, skip as boolean)).toBe(expected)
})
it('defines a week as five business days or seven calendar days', () => {
  expect(quickReminderDate('2026-11-06', 7, true)).toBe('2026-11-13')
  expect(quickReminderDate('2026-11-06', 7, false)).toBe('2026-11-13')
})
it('rejects invalid dates and negative/fractional day counts', () => {
  for (const [date, days] of [
    ['bad', 1],
    ['2026-02-30', 1],
    ['2026-11-03', -1],
    ['2026-11-03', 1.5],
  ] as const)
    expect(() => addBusinessDays(date, days)).toThrow()
})
it('resolves IANA local time including DST gaps/overlaps', () => {
  expect(reminderInstant('2026-03-08', '02:30', 'America/Toronto')).toBeNull()
  expect(reminderInstant('2026-11-01', '01:30', 'America/Toronto')).toBe('2026-11-01T05:30:00.000Z')
  expect(reminderInstant('2026-11-05', '09:00', 'Asia/Ho_Chi_Minh')).toBe(
    '2026-11-05T02:00:00.000Z',
  )
})
it('enforces today through 90 days and future instants', () => {
  const now = new Date('2026-11-03T08:00:00Z')
  expect(validateReminder('2026-11-03', '14:00', 'Asia/Ho_Chi_Minh', now)).toBe('taskUi.futureTime')
  expect(validateReminder('2027-02-02', '09:00', 'Asia/Ho_Chi_Minh', now)).toBe('taskUi.dateRange')
  expect(validateReminder('2026-11-04', '09:00', 'Asia/Ho_Chi_Minh', now)).toBeNull()
})
it('gives safe preferences and an English zoned confirmation', () => {
  expect(reminderPreferences(null)).toMatchObject({
    timezone: 'Asia/Ho_Chi_Minh',
    default_remind_time: '09:00',
    task_sound: false,
    web_notifications: false,
    skip_weekends: true,
  })
  expect(confirmation('2026-11-05', '09:00', 'Asia/Ho_Chi_Minh')).toMatchObject({
    weekday: 'Thu',
    date: '05 Nov 2026',
  })
})
