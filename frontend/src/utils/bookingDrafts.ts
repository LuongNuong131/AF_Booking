import { timeouts } from '../config/timeouts'
import { readStorage, writeStorage } from './storage'
export interface BookingDraft {
  status_code: string
  note: string
  at: number
  invoice_text?: string
  no_invoice?: boolean
}
export function draftStorage(userId: number) {
  const storageKey = `booking.drafts.v1.${userId}`
  function read(): Record<string, BookingDraft> {
    let raw: unknown
    try {
      raw = JSON.parse(readStorage('localStorage', storageKey) ?? '{}')
    } catch {
      return {}
    }
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {}
    return Object.fromEntries(
      Object.entries(raw).filter(([, value]: [string, unknown]) => {
        if (!value || typeof value !== 'object') return false
        const d = value as Partial<BookingDraft>
        return (
          typeof d.status_code === 'string' &&
          d.status_code.length <= 40 &&
          typeof d.note === 'string' &&
          d.note.length <= 5000 &&
          (d.invoice_text === undefined ||
            (typeof d.invoice_text === 'string' && d.invoice_text.length <= 2000)) &&
          (d.no_invoice === undefined || typeof d.no_invoice === 'boolean') &&
          typeof d.at === 'number' &&
          d.at <= Date.now() &&
          Date.now() - d.at < timeouts.draftLifetime
        )
      }),
    )
  }
  function save(
    key: string,
    status_code: string,
    note: string,
    invoice_text = '',
    no_invoice = false,
  ) {
    const values = read()
    if (status_code || note || invoice_text || no_invoice)
      values[key] = {
        status_code,
        note,
        invoice_text,
        no_invoice,
        at: Date.now(),
      }
    else delete values[key]
    const bounded = Object.fromEntries(
      Object.entries(values)
        .sort(([, a], [, b]) => b.at - a.at)
        .slice(0, 100),
    )
    return writeStorage('localStorage', storageKey, JSON.stringify(bounded))
  }
  function get(key: string) {
    return read()[key] ?? null
  }
  function discard(key: string) {
    return save(key, '', '')
  }
  return { get, save, discard }
}
