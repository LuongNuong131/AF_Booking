import { normalizeBookingKey, parseBookingKey } from './bookingKey'

export type QueryKind =
  | 'invoice'
  | 'full_key'
  | 'partial_key'
  | 'cw_number'
  | 'cw_prefix'
  | 'station_period'
  | 'station'
  | 'text'
  | 'none'
export interface ClassifiedQuery {
  kind: QueryKind
  query: string
  cw_number?: string
  station_code?: string
  period?: string
}
export function normalizeSearch(raw: string): string {
  return raw
    .replace(/[\p{Cc}\p{Cf}]/gu, (c) => (/\s/.test(c) ? c : ''))
    .replace(/[–—−‐‑]/g, '-')
    .trim()
    .replace(/\s+/g, ' ')
    .toUpperCase()
}
export function classifyQuery(
  raw: string,
  stations: readonly string[] = [],
  stationPattern = '[A-Z]{3}',
): ClassifiedQuery {
  const query = normalizeSearch(raw)
  if (!query || raw.length > 100) return { kind: 'none', query }
  if (query.startsWith('INV:') || query.startsWith('#')) return { kind: 'invoice', query }
  const parsed = parseBookingKey(raw, stationPattern)
  if (parsed)
    return {
      kind: 'key' in parsed ? 'full_key' : 'partial_key',
      query: 'key' in parsed ? parsed.key : parsed.normalized,
      cw_number: parsed.cw_number,
      ...('key' in parsed ? { station_code: parsed.station_code } : {}),
      period: parsed.period,
    }
  const key = normalizeBookingKey(raw),
    pattern = new RegExp(`^(?:${stationPattern})$`)
  const cw = /^(CW[0-9]{0,10})(?:-([A-Z]{1,4}))?$/.exec(key)
  if (cw && (!cw[2] || pattern.test(cw[2])))
    return {
      kind: cw[1]!.length >= 7 ? 'cw_number' : 'cw_prefix',
      query: key,
      cw_number: cw[1],
      station_code: cw[2],
    }
  const sp = /^([A-Z]{1,4})-([0-9]{2}(?:0[1-9]|1[0-2]))$/.exec(key)
  if (sp && pattern.test(sp[1]!))
    return {
      kind: 'station_period',
      query: key,
      station_code: sp[1],
      period: sp[2],
    }
  if (pattern.test(query) && stations.includes(query))
    return { kind: 'station', query, station_code: query }
  if (/^CW(?:[0-9]|-|$)/.test(key) || /^[A-Z]{1,4}-[0-9]{4}$/.test(key))
    return { kind: 'none', query: key }
  return { kind: 'text', query }
}
