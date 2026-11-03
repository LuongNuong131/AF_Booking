import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory, type Router } from 'vue-router'
import { api } from '../api/client'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { statuses, user, item } from '../test/bookingFixtures'
import SummaryView from './SummaryView.vue'
let wrapper: VueWrapper | undefined, router: Router
beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  useAuthStore().user = user
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { render: () => null } },
      { path: '/summary', name: 'summary', component: SummaryView },
    ],
  })
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.useRealTimers()
  vi.restoreAllMocks()
})
async function render() {
  await router.push('/summary')
  wrapper = mount(SummaryView, { global: { plugins: [router, i18n] } })
  await flushPromises()
}
function basicMock() {
  return vi.spyOn(api, 'get').mockImplementation(async (url) => ({
    data:
      url === '/statuses'
        ? statuses
        : url === '/users/lookup'
          ? []
          : { items: [], total: 0, page: 1, size: 20 },
  }))
}
it('does not navigate back or send a debounced request after leaving the page', async () => {
  const get = basicMock()
  await render()
  await wrapper!.get('input[placeholder^="Search booking"]').setValue('Hotel')
  wrapper!.unmount()
  wrapper = undefined
  await router.push('/')
  const calls = get.mock.calls.length
  await vi.advanceTimersByTimeAsync(500)
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/')
  expect(get).toHaveBeenCalledTimes(calls)
})
it('cancels immediately when typing, debounces the URL and ignores an older list response', async () => {
  let finish!: (value: unknown) => void,
    signal: AbortSignal | undefined,
    count = 0
  vi.spyOn(api, 'get').mockImplementation((url, config) => {
    if (url === '/statuses') return Promise.resolve({ data: statuses })
    if (url === '/users/lookup') return Promise.resolve({ data: [] })
    if (++count === 1) {
      signal = config?.signal as AbortSignal
      return new Promise((done) => {
        finish = done
      })
    }
    return Promise.resolve({
      data: { items: [item(2)], total: 1, page: 1, size: 20 },
    })
  })
  await render()
  await wrapper!.get('input[placeholder^="Search booking"]').setValue('Hotel')
  expect(signal?.aborted).toBe(true)
  await vi.advanceTimersByTimeAsync(300)
  await flushPromises()
  expect(router.currentRoute.value.query.q).toBe('Hotel')
  finish({ data: { items: [], total: 0, page: 1, size: 20 } })
  await flushPromises()
  expect(wrapper!.findAll('tbody tr')).toHaveLength(1)
})
