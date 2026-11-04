export interface ParsedKey {
  key: string
  display_key: string
  cw_number: string
  station_code: string
  period: string
  period_label: string
}
export interface PartialKey {
  cw_number: string
  period: string
  period_label: string
  normalized: string
}
const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const maxLength = 100

export function normalize(raw: string): string {
  if (raw.length > maxLength) return ''
  return raw
    .replace(/[\p{Cc}\p{Cf}]/gu, '')
    .replace(/[–—−‐‑]/g, '-')
    .trim()
    .toUpperCase()
    .replace(/\s*-\s*/g, '-')
    .replace(/^CW\s+(?=[0-9])/, 'CW')
    .replace(/\s+/g, '-')
}
export function to_display(key: string): string {
  return key.replace(/^CW\s*(?=[0-9])/, 'CW ')
}
function label(period: string): string {
  return `${months[Number(period.slice(2)) - 1]} ${2000 + Number(period.slice(0, 2))}`
}
export function parse(raw: string, stationPattern = '[A-Z]{3}'): ParsedKey | PartialKey | null {
  if (raw.length > maxLength || /\p{Cc}/u.test(raw)) return null
  const key = normalize(raw)
  const partial = /^(CW[0-9]{5,10})-([0-9]{2}(?:0[1-9]|1[0-2]))$/.exec(key)
  if (partial)
    return {
      cw_number: partial[1]!,
      period: partial[2]!,
      period_label: label(partial[2]!),
      normalized: key,
    }
  const full = /^(CW[0-9]{5,10})-([A-Z]{1,4})-([0-9]{2}(?:0[1-9]|1[0-2]))$/.exec(key)
  if (!full || !new RegExp(`^(?:${stationPattern})$`).test(full[2]!)) return null
  return {
    key,
    display_key: to_display(key),
    cw_number: full[1]!,
    station_code: full[2]!,
    period: full[3]!,
    period_label: label(full[3]!),
  }
}
export function build_key(
  cw: string,
  station: string,
  period: string,
  stationPattern = '[A-Z]{3}',
): string {
  const result = parse(`${cw}-${station}-${period}`, stationPattern)
  if (!result || !('key' in result)) throw new Error('Invalid booking key components')
  return result.key
}

// Public names for every component/composable; existing exports remain compatible.
export const parseBookingKey = parse
export const normalizeBookingKey = normalize
export const formatBookingKey = to_display
