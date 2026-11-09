import { afterEach, describe, expect, it } from 'vitest'
import en from './locales/en.json'
import vi from './locales/vi.json'
import { i18n, setLanguage, validLanguage } from './i18n'

afterEach(() => setLanguage('en'))
function strings(value: object, prefix = ''): Record<string, string> {
  return Object.fromEntries(Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof child === 'string' ? [[path, child]] : Object.entries(strings(child, path))
  }))
}
it('covers every English key and preserves interpolation and linked messages in Vietnamese', () => {
  const source = strings(en), translated = strings(vi)
  expect(Object.keys(translated).sort()).toEqual(Object.keys(source).sort())
  for (const [key, value] of Object.entries(source)) {
    expect(translated[key]?.trim(), key).toBeTruthy()
    expect([...translated[key]!.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort(), key)
      .toEqual([...value.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort())
    if (value.startsWith('@:')) expect(translated[key]).toBe(value)
  }
})
it('defaults invalid preferences to English and persists an explicit language choice', () => {
  expect(validLanguage('fr')).toBe('en')
  setLanguage('vi')
  expect(i18n.global.t('auth.signIn')).toBe('Đăng nhập')
  expect(i18n.global.t('tasks_due_modal', { n: 3 })).toContain('3')
  expect(localStorage.getItem('booking.language')).toBe('vi')
  setLanguage('en')
  expect(i18n.global.t('auth.signIn')).toBe('Sign in')
})

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
