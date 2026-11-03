import { afterEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { useTasksStore } from '../stores/tasks'
import { KEY, user } from '../test/bookingFixtures'
import TaskSuggestionBar from './TaskSuggestionBar.vue'
afterEach(() => vi.useRealTimers())
it('shows the status-specific date and preselects that reminder in one click', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-11-03T08:00:00Z'))
  setActivePinia(createPinia())
  useAuthStore().user = {
    ...user,
    settings: { timezone: 'UTC', default_remind_time: '09:00', skip_weekends: false },
  }
  const wrapper = mount(TaskSuggestionBar, {
    props: { bookingKey: KEY, nonce: 1, days: 3 },
    global: { plugins: [i18n] },
  })
  expect(wrapper.text()).toContain('Remind in 3 days')
  expect(wrapper.text()).toContain('Fri, 06 Nov 2026 09:00:00 UTC')
  await wrapper.find('button').trigger('click')
  expect(useTasksStore().dialog).toMatchObject({ key: KEY, presetDays: 3, mode: 'create' })
  wrapper.unmount()
})

it('does not suggest a task automatically when status reminder days are null', () => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  useAuthStore().user = user
  const wrapper = mount(TaskSuggestionBar, {
    props: { bookingKey: KEY, nonce: 1, days: null },
    global: { plugins: [i18n] },
  })
  expect(wrapper.find('.task-suggestion-bar').exists()).toBe(false)
  wrapper.unmount()
})
