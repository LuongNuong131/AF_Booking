import { zonedToday } from './summaryFilters'
import { formatDateTime, validTimeZone } from './dateTime'
export interface ReminderPreferences {
  timezone: string
  default_remind_time: string
  task_sound: boolean
  web_notifications: boolean
  skip_weekends: boolean
  auto_watch_on_note?: boolean
}
export function reminderPreferences(value: unknown): ReminderPreferences {
  const settings = value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
  return {
    timezone: validTimeZone(settings.timezone, 'Asia/Ho_Chi_Minh'),
    default_remind_time:
      typeof settings.default_remind_time === 'string' &&
      /^([01]\d|2[0-3]):[0-5]\d$/.test(settings.default_remind_time)
        ? settings.default_remind_time
        : '09:00',
    auto_watch_on_note: settings.auto_watch_on_note === true,
    task_sound: settings.task_sound === true,
    web_notifications: settings.web_notifications === true,
    skip_weekends: settings.skip_weekends !== false,
  }
}
export function addBusinessDays(day: string, days: number, skipWeekends = true): string {
  if (!Number.isInteger(days) || days < 0 || days > 90 || !/^\d{4}-\d{2}-\d{2}$/.test(day))
    throw new Error('Invalid reminder day')
  const date = new Date(day + 'T12:00:00Z')
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== day)
    throw new Error('Invalid reminder day')
  let left = days
  while (left > 0) {
    date.setUTCDate(date.getUTCDate() + 1)
    if (!skipWeekends || ![0, 6].includes(date.getUTCDay())) left--
  }
  return date.toISOString().slice(0, 10)
}
export function reminderParts(instant: string, zone: string) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: zone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(instant))
  const p = (key: Intl.DateTimeFormatPartTypes) => parts.find((v) => v.type === key)!.value
  return {
    date: `${p('year')}-${p('month')}-${p('day')}`,
    time: `${p('hour')}:${p('minute')}`,
  }
}
export function reminderInstant(day: string, clock: string, zone: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !/^([01]\d|2[0-3]):[0-5]\d$/.test(clock)) return null
  const base = Date.parse(`${day}T${clock}:00Z`)
  if (!Number.isFinite(base) || new Date(base).toISOString().slice(0, 10) !== day) return null
  const offsets = new Set<number>()
  for (const hours of [-36, -12, 0, 12, 36]) {
    const sample = base + hours * 3600000,
      parts = reminderParts(new Date(sample).toISOString(), zone)
    offsets.add(Date.parse(`${parts.date}T${parts.time}:00Z`) - sample)
  }
  const candidates = [...offsets]
    .map((offset) => base - offset)
    .filter((value) => {
      const p = reminderParts(new Date(value).toISOString(), zone)
      return p.date === day && p.time === clock
    })
    .sort((a, b) => a - b)
  return candidates.length ? new Date(candidates[0]!).toISOString() : null
}
export function validateReminder(
  day: string,
  clock: string,
  zone: string,
  now = new Date(),
): string | null {
  const today = zonedToday(zone, now)
  if (!day || day < today || day > addBusinessDays(today, 90, false)) return 'taskUi.dateRange'
  const instant = reminderInstant(day, clock, zone)
  if (!instant) return 'taskUi.invalidLocalTime'
  if (Date.parse(instant) <= now.getTime()) return 'taskUi.futureTime'
  return null
}
export function confirmation(day: string, clock: string, zone: string) {
  const instant = reminderInstant(day, clock, zone)
  if (!instant) return null
  const text = formatDateTime(instant, zone)
  return {
    weekday: new Intl.DateTimeFormat('en-GB', {
      weekday: 'short',
      timeZone: zone,
    }).format(new Date(instant)),
    date: text.slice(0, 11),
    time: text.slice(12),
  }
}

export function quickReminderDate(day: string, days: number, skip: boolean) {
  return addBusinessDays(day, days === 7 && skip ? 5 : days, skip)
}
