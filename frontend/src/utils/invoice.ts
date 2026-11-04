export const INVOICE_PATTERN = '^[A-Z0-9][A-Z0-9\\-_/.]{2,39}$'
export function normalizeInvoice(value: string): string {
  return value
    .replace(/[\p{Cc}\p{Cf}]/gu, '')
    .trim()
    .toUpperCase()
}
export function parseInvoiceInput(raw: string): string[] {
  return [
    ...new Set(
      raw
        .split(/[,;\s]+/)
        .map(normalizeInvoice)
        .filter(Boolean),
    ),
  ]
}
export function validInvoice(value: string, pattern = INVOICE_PATTERN): boolean {
  try {
    return value.length <= 40 && new RegExp(`^(?:${pattern})$`).test(value)
  } catch {
    return false
  }
}
