import { afterEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { api } from '../../api/client'
import { useAuthStore } from '../../stores/auth'
import { user } from '../../test/bookingFixtures'
import { i18n } from '../../i18n'
import AdminIntegrity from './AdminIntegrity.vue'
afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})
it('waits for explicit confirmation before repairing and releases its progress timer', async () => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  useAuthStore().user = { ...user, role: 'admin' }
  const run = {
    id: 1,
    started_at: '2026-11-03T08:00:00.000Z',
    finished_at: '2026-11-03T08:00:01.000Z',
    checked: 10,
    mismatched: 1,
    fixed: 0,
    status: 'completed',
    details: { mode: 'report', trigger: 'manual', items: [] },
  }
  vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [run], total: 1, page: 1, size: 20 } })
  let finish!: (v: unknown) => void
  const post = vi.spyOn(api, 'post').mockImplementation(
    () =>
      new Promise((done) => {
        finish = done
      }),
  )
  const wrapper = mount(AdminIntegrity, {
    global: {
      plugins: [i18n],
      stubs: {
        ElDialog: defineComponent({
          props: { modelValue: Boolean },
          template: '<div v-if="modelValue"><slot/><slot name="footer"/></div>',
        }),
      },
    },
  })
  await flushPromises()
  await wrapper
    .findAll('button')
    .find((b) => b.text() === 'Fix mismatched bookings')!
    .trigger('click')
  expect(post).not.toHaveBeenCalled()
  await wrapper
    .findAll('button')
    .find((b) => b.text() === 'Start repairs')!
    .trigger('click')
  await flushPromises()
  expect(post).toHaveBeenCalledWith('/admin/integrity/fix', { run_id: 1 }, expect.any(Object))
  expect(wrapper.text()).toContain('Fixed: 0')
  finish({ data: { ...run, id: 2 } })
  await flushPromises()
  wrapper.unmount()
  const reads = vi.mocked(api.get).mock.calls.length
  await vi.advanceTimersByTimeAsync(5000)
  expect(api.get).toHaveBeenCalledTimes(reads)
})
