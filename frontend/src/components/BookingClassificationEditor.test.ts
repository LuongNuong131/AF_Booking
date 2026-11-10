import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { i18n } from '../i18n'
import { api } from '../api/client'
import { item, KEY } from '../test/bookingFixtures'
import BookingClassificationEditor from './BookingClassificationEditor.vue'
beforeEach(() => { setActivePinia(createPinia()); i18n.global.locale.value = 'en' })
afterEach(() => vi.restoreAllMocks())
function render(type: 'hotel' | 'unclassified' = 'hotel') {
  return mount(BookingClassificationEditor, { props: { bookingKey: KEY, type }, global: { plugins: [i18n], stubs: { ElDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /></div>' } } } })
}
it('classifies the selected booking using the current type as a concurrency check', async () => {
  const value = item(); value.supplier.type = 'transportation'
  const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: value })
  const wrapper = render()
  await wrapper.get('.classification-trigger').trigger('click')
  expect(wrapper.text()).toContain('Other monthly bookings keep their own classification')
  await wrapper.get('select').setValue('transportation')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(patch).toHaveBeenCalledWith(`/bookings/${KEY}/classification`, { supplier_type: 'transportation', expected_type: 'hotel' }, expect.any(Object))
  expect(wrapper.emitted('updated')).toHaveLength(1)
  expect(wrapper.text()).toContain('Booking classification saved')
  wrapper.unmount()
})
it('can classify an unclassified booking and cancel without writing', async () => {
  const patch = vi.spyOn(api, 'patch')
  const wrapper = render('unclassified')
  expect(wrapper.get('.classification-trigger').text()).toBe('Classify booking')
  await wrapper.get('.classification-trigger').trigger('click')
  await wrapper.get('select').setValue('hotel')
  await wrapper.get('button[type="button"]:not(.classification-trigger)').trigger('click')
  expect(patch).not.toHaveBeenCalled()
  expect(wrapper.find('form').exists()).toBe(false)
  wrapper.unmount()
})
it('keeps the selection and a recoverable error after a rejected save', async () => {
  vi.spyOn(api, 'patch').mockRejectedValue(new Error('Failed'))
  const wrapper = render()
  await wrapper.get('.classification-trigger').trigger('click')
  await wrapper.get('select').setValue('transportation')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  expect((wrapper.get('select').element as HTMLSelectElement).value).toBe('transportation')
  wrapper.unmount()
})
