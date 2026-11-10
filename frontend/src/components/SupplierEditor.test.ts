import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { i18n } from '../i18n'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { user } from '../test/bookingFixtures'
import SupplierEditor from './SupplierEditor.vue'
beforeEach(() => { setActivePinia(createPinia()); useAuthStore().user = { ...user }; i18n.global.locale.value = 'en' })
afterEach(() => vi.restoreAllMocks())
function render(type: 'hotel' | 'unclassified' = 'hotel') {
  return mount(SupplierEditor, { props: { cw: 'CW2154654-RDU', name: 'Example Hotel', type }, global: { plugins: [i18n] } })
}
it.each(['agent', 'qc', 'admin'] as const)('lets %s change classification with only the type field', async role => {
  useAuthStore().user!.role = role
  const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: {
    cw_number: 'CW2154654', station_code: 'RDU', supplier_name: 'Example Hotel', supplier_type: 'transportation', recurring_enabled: true,
  } })
  const wrapper = render()
  await wrapper.get('.classification-trigger').trigger('click')
  expect(wrapper.find('input').exists()).toBe(false)
  expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  await wrapper.get('select').setValue('transportation')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(patch).toHaveBeenCalledWith('/folders/CW2154654-RDU', { supplier_type: 'transportation' }, expect.any(Object))
  expect(wrapper.get('[role="status"]').text()).toContain('classification updated')
  expect(wrapper.emitted('updated')).toHaveLength(1)
  wrapper.unmount()
})
it('supports classifying imported unclassified folders and cancelling without saving', async () => {
  const patch = vi.spyOn(api, 'patch')
  const wrapper = render('unclassified')
  await wrapper.get('.classification-trigger').trigger('click')
  expect(wrapper.get('option[value="unclassified"]').attributes('disabled')).toBeDefined()
  await wrapper.get('select').setValue('hotel')
  await wrapper.get('button[type="button"]').trigger('click')
  expect(wrapper.find('form').exists()).toBe(false)
  expect(patch).not.toHaveBeenCalled()
  wrapper.unmount()
})
it('keeps failed edits available and prevents a late response from affecting another folder', async () => {
  let finish!: (value: unknown) => void
  vi.spyOn(api, 'patch').mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const wrapper = render()
  await wrapper.get('.classification-trigger').trigger('click')
  await wrapper.get('select').setValue('transportation')
  await wrapper.get('form').trigger('submit')
  expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
  await wrapper.setProps({ cw: 'CW2154655-YUL', type: 'hotel' })
  finish({ data: { supplier_type: 'transportation' } })
  await flushPromises()
  expect(wrapper.emitted('updated')).toBeUndefined()
  expect(wrapper.find('form').exists()).toBe(false)
  wrapper.unmount()
})
it('shows a recoverable error and keeps the selected classification', async () => {
  vi.spyOn(api, 'patch').mockRejectedValue(new Error('Failed'))
  const wrapper = render()
  await wrapper.get('.classification-trigger').trigger('click')
  await wrapper.get('select').setValue('transportation')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  expect((wrapper.get('select').element as HTMLSelectElement).value).toBe('transportation')
  expect(wrapper.emitted('updated')).toBeUndefined()
  wrapper.unmount()
})
