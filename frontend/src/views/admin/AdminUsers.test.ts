import { afterEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import { i18n } from '../../i18n'
import { api } from '../../api/client'
import { useAuthStore } from '../../stores/auth'
import AdminUsers from './AdminUsers.vue'
afterEach(() => vi.restoreAllMocks())
it('disables self-lock and self-demotion controls for the current admin', async () => {
  setActivePinia(createPinia())
  useAuthStore().user = {
    id: 1,
    username: 'admin',
    full_name: 'Administrator',
    role: 'admin',
    is_active: true,
    settings: null,
  }
  vi.spyOn(api, 'get').mockResolvedValue({
    data: {
      items: [
        {
          id: 1,
          username: 'admin',
          full_name: 'Administrator',
          role: 'admin',
          is_active: true,
          last_login_at: null,
          created_at: '2026-11-03T00:00:00Z',
          has_session: true,
        },
      ],
      total: 1,
      page: 1,
      size: 20,
    },
  })
  const wrapper = mount(AdminUsers, {
    global: {
      plugins: [i18n],
      stubs: { ElDialog: { template: '<section><slot /></section>' } },
    },
  })
  await flushPromises()
  const buttons = wrapper.findAll('tbody button')
  expect(buttons.find((b) => b.text() === 'Disable')?.attributes('disabled')).toBeDefined()
  await buttons.find((b) => b.text() === 'Edit')!.trigger('click')
  expect(wrapper.get('select').attributes('disabled')).toBeDefined()
  wrapper.unmount()
})
