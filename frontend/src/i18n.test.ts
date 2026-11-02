import { describe, expect, it } from 'vitest'
import en from './locales/en.json'
import { i18n } from './i18n'

describe('Prompt 1B UI copy', () => {
  it('interpolates the variables in every shared string', () => {
    for (const [key, value] of Object.entries(en)) {
      if (typeof value !== 'string') continue
      const params = Object.fromEntries([...value.matchAll(/\{(\w+)\}/g)]
        .map((match) => [match[1], 'Example']))
      const rendered = i18n.global.t(key, params)
      expect(rendered).toBe(value.replace(/\{\w+\}/g, 'Example'))
    }
  })
  it('preserves the required invoice labels and separate warmup states', () => {
    expect(i18n.global.t('no_invoice_checkbox')).toBe('No invoice Number')
    expect(i18n.global.t('invoice_required_hint'))
      .toBe('Add at least one invoice number or tick "No invoice Number".')
    expect(i18n.global.t('warmup')).toBe('Waking up the server…')
    expect(i18n.global.t('warmup_ready')).toBe('Ready')
  })
})
