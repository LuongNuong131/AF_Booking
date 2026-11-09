import { createI18n } from 'vue-i18n'
import en from './locales/en.json'
import vi from './locales/vi.json'
import { readStorage, writeStorage } from './utils/storage'

export type Language = 'en' | 'vi'
export function validLanguage(value: unknown): Language {
  return value === 'vi' ? 'vi' : 'en'
}
export const i18n = createI18n({
  legacy: false,
  locale: validLanguage(readStorage('localStorage', 'booking.language')),
  fallbackLocale: 'en',
  messages: { en, vi },
})
export function setLanguage(value: unknown): void {
  const language = validLanguage(value)
  i18n.global.locale.value = language
  writeStorage('localStorage', 'booking.language', language)
}
