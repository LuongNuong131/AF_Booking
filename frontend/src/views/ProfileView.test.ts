import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { user } from '../test/bookingFixtures'
import ProfileView from './ProfileView.vue'
import { api } from '../api/client'
import { createRouter, createMemoryHistory } from 'vue-router'
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', component: ProfileView },
    { path: '/login', name: 'login', component: { template: '<div />' } },
  ],
})
beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().user = user
  vi.spyOn(api, 'get').mockResolvedValue({
    data: {
      notes_today: 0,
      notes_week: 0,
      timezone: 'America/Toronto',
      login_history: [],
    },
  })
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
it('requests Notification permission only after the user enables it', async () => {
  const permission = vi.fn().mockResolvedValue('denied')
  vi.stubGlobal(
    'Notification',
    class {
      static permission = 'default'
      static requestPermission = permission
    },
  )
  const wrapper = mount(ProfileView, { global: { plugins: [i18n, router] } })
  expect(permission).not.toHaveBeenCalled()
  await wrapper.findAll('.preference-toggle input')[2]!.setValue(true)
  await flushPromises()
  expect(permission).toHaveBeenCalledTimes(1)
  expect(
    (wrapper.findAll('.preference-toggle input')[2]!.element as HTMLInputElement).checked,
  ).toBe(false)
  expect(wrapper.text()).toContain('Notifications were not enabled.')
  wrapper.unmount()
})
it('rejects mismatched new passwords before calling the API', async () => {
  const post = vi.spyOn(api, 'post'),
    wrapper = mount(ProfileView, { global: { plugins: [i18n, router] } })
  const fields = wrapper.findAll('.profile-password-form input')
  await fields[0]!.setValue('current-password')
  await fields[1]!.setValue('new-password-one')
  await fields[2]!.setValue('new-password-two')
  await wrapper.get('.profile-password-form').trigger('submit')
  expect(wrapper.text()).toContain('The new passwords do not match.')
  expect(post).not.toHaveBeenCalled()
  wrapper.unmount()
})
it('saves only the display name and updates the current account', async () => {
  const patch = vi
    .spyOn(api, 'patch')
    .mockResolvedValue({ data: { ...user, full_name: 'Updated Name' } })
  const wrapper = mount(ProfileView, { global: { plugins: [i18n, router] } })
  await wrapper.get('.profile-name-form input').setValue('Updated Name')
  await wrapper.get('.profile-name-form').trigger('submit')
  await flushPromises()
  expect(patch.mock.calls[0]?.[1]).toEqual({ full_name: 'Updated Name' })
  expect(useAuthStore().user?.full_name).toBe('Updated Name')
  wrapper.unmount()
})
