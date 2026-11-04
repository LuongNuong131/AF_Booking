import { it, expect } from 'vitest'
import cases from '../../../fixtures/invoice-input.json'
import { parseInvoiceInput, normalizeInvoice, validInvoice } from './invoice'
for (const row of cases)
  it(`shares invoice input parsing: ${JSON.stringify(row.raw)}`, () =>
    expect(parseInvoiceInput(row.raw)).toEqual(row.expected))
it('normalizes controls and validates the leading alphanumeric and custom pattern', () => {
  expect(normalizeInvoice(' inv\0a\u200b01 ')).toBe('INVA01')
  for (const value of ['_BAD', 'AB', '=1+1', 'A'.repeat(41), 'A@B'])
    expect(validInvoice(value)).toBe(false)
  expect(validInvoice('INV/123-A.2')).toBe(true)
  expect(validInvoice('1234', '^[0-9]{4}$')).toBe(true)
  expect(validInvoice('INV1', '^[0-9]{4}$')).toBe(false)
})
