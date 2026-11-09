import { afterEach, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { i18n, setLanguage } from '../i18n'
import { parseBookingKey } from '../utils/bookingKey'
import { classifyQuery } from '../utils/searchQuery'
import { isFolderKey } from '../utils/folderKey'
import LanguageSelect from './LanguageSelect.vue'
afterEach(() => { vi.restoreAllMocks(); setLanguage('en') })
it('changes language in place and remains usable when browser storage is unavailable', async () => {
  const wrapper = mount(LanguageSelect, { global: { plugins: [i18n] } })
  await wrapper.get('select').setValue('vi')
  expect(wrapper.get('label').text()).toContain('Ngôn ngữ')
  expect(localStorage.getItem('booking.language')).toBe('vi')
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
  await wrapper.get('select').setValue('en')
  expect(i18n.global.locale.value).toBe('en')
  wrapper.unmount()
})
it.each(['CWXXXXXXX1-PTP-2609', 'CWXXXX-LAS-2609'])('supports special keys consistently: %s', key => {
  expect(parseBookingKey(key)).toMatchObject({ key })
  expect(classifyQuery(key).kind).toBe('full_key')
  const folder = key.slice(0, -5)
  expect(isFolderKey(folder)).toBe(true)
  expect(classifyQuery(folder).kind).toBe('cw_number')
})
