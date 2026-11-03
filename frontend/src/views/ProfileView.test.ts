import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { user } from '../test/bookingFixtures'
import ProfileView from './ProfileView.vue'
beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().user = user
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
  const wrapper = mount(ProfileView, { global: { plugins: [i18n] } })
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
