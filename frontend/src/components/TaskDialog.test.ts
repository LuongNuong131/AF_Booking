import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'
import { api } from '../api/client'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { useTasksStore } from '../stores/tasks'
import { user, KEY, task } from '../test/bookingFixtures'
import TaskDialog from './TaskDialog.vue'
let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-11-03T08:00:00Z'))
  setActivePinia(createPinia())
  useAuthStore().user = { ...user, settings: { timezone: 'Asia/Ho_Chi_Minh' } }
  vi.spyOn(api, 'get').mockResolvedValue({ data: [] })
  useTasksStore().openDialog(KEY)
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  useTasksStore().reset()
  vi.restoreAllMocks()
  vi.useRealTimers()
})
function render() {
  wrapper = mount(TaskDialog, {
    global: {
      plugins: [i18n],
      stubs: {
        ElDialog: defineComponent({
          template: '<section><slot name="header" /><slot /><slot name="footer" /></section>',
        }),
      },
    },
  })
  return wrapper
}
it('shows a zoned confirmation and rejects dates in the past without a request', async () => {
  const post = vi.spyOn(api, 'post')
  render()
  await flushPromises()
  expect(wrapper!.get('.task-confirmation').text()).toContain('Wed, 04 Nov 2026 09:00:00')
  await wrapper!.get('input[type=date]').setValue('2020-01-01')
  await wrapper!.get('form').trigger('submit')
  expect(wrapper!.text()).toContain('Choose a date from today through 90 days ahead.')
  expect(post).not.toHaveBeenCalled()
})
it('keeps fields editable through failure and reuses the UUID on explicit retry', async () => {
  const config = { method: 'post', headers: new AxiosHeaders() } as InternalAxiosRequestConfig
  const post = vi
    .spyOn(api, 'post')
    .mockRejectedValue(new AxiosError('timeout', 'ECONNABORTED', config))
  render()
  await flushPromises()
  await wrapper!.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper!.get('input[type=date]').attributes('disabled')).toBeUndefined()
  expect(wrapper!.text()).toContain('This is taking too long.')
  await wrapper!.get('form').trigger('submit')
  await flushPromises()
  expect(post.mock.calls[0]?.[1]).toEqual(post.mock.calls[1]?.[1])
  expect(post.mock.calls[0]?.[1]).toMatchObject({ remind_date: '2026-11-04', remind_time: '09:00' })
})
it('allows editing an overdue message while keeping its existing reminder date', async () => {
  const old = { ...task(), remind_at: '2026-11-02T01:00:00.000Z' }
  useTasksStore().openDialog(KEY, old, 'edit')
  vi.spyOn(api, 'get').mockResolvedValue({ data: [old] })
  render()
  await flushPromises()
  expect(wrapper!.get('input[type=date]').attributes('min')).toBe('2026-11-02')
  expect(wrapper!.get('button[type=submit]').attributes('disabled')).toBeUndefined()
  expect(wrapper!.find('.field-error').exists()).toBe(false)
})
