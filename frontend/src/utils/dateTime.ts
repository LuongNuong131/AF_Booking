import { isValid, parseISO } from 'date-fns'
import { i18n } from '../i18n'

export function validTimeZone(value: unknown, fallback = 'UTC'): string {
  if (typeof value === 'string') {
    try {
      new Intl.DateTimeFormat('en-GB', { timeZone: value }).format()
      return value
    } catch {
      /* Fall through. */
    }
  }
  return fallback
}
export function formatDateTime(value: string | Date, timeZone = 'UTC'): string {
  const date = typeof value === 'string' ? parseISO(value) : value
  if (!isValid(date)) return ''
  const parts = new Intl.DateTimeFormat(i18n.global.locale.value === 'vi' ? 'vi-VN' : 'en-GB', {
    timeZone: validTimeZone(timeZone),
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
    timeZoneName: 'short',
  }).formatToParts(date)
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? ''
  return `${part('day')} ${part('month')} ${part('year')} ${part('hour')}:${part('minute')}:${part('second')} ${part('timeZoneName')}`
}
