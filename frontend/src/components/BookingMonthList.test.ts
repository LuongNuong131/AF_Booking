import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { user } from '../test/bookingFixtures'
import { months } from '../test/folderFixtures'
import BookingMonthList from './BookingMonthList.vue'
it('shows twenty first and enables windowed scrolling for folders over fifty months', async () => {
  setActivePinia(createPinia())
  useAuthStore().user = user
  const rows = Array.from({ length: 60 }, (_, i) => ({
    ...months()[0]!,
    booking_key: `CW2154927-YUL-${String(2000 + Math.floor(i / 12)).slice(-2)}${String((i % 12) + 1).padStart(2, '0')}`,
  }))
  const wrapper = mount(BookingMonthList, {
    props: { months: rows },
    global: { plugins: [i18n] },
  })
  expect(wrapper.find('.month-list.virtual').exists()).toBe(true)
  expect(wrapper.text()).toContain('Showing 20 of 60 month(s)')
  expect(wrapper.findAll('.month-row').length).toBeLessThan(20)
  await wrapper.get('.month-list-footer button').trigger('click')
  expect(wrapper.text()).toContain('Showing 40 of 60 month(s)')
  wrapper.unmount()
})
