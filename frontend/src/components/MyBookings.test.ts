import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { api } from '../api/client'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { useBookingsStore } from '../stores/bookings'
import { event, item, lookup, user, statuses, KEY } from '../test/bookingFixtures'
import MyBookings from './MyBookings.vue'
let wrapper: VueWrapper | undefined
beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().user = user
  useAuthStore().token = 'test'
  useBookingsStore().statuses = statuses
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
})
const render = () => (wrapper = mount(MyBookings, { global: { plugins: [i18n] } }))
it('uses 10-row server pages and counts new self updates on later pages without hydrating them', async () => {
  const get = vi.spyOn(api, 'get').mockImplementation(async (url, config) => {
    if (url === '/bookings/stale') return { data: { items: [], total: 0, page: 1, size: 1 } }
    return {
      data: {
        items: [item()],
        total: 11,
        page: (config?.params as { page?: number } | undefined)?.page ?? 1,
        size: (config?.params as { size?: number } | undefined)?.size,
      },
    }
  })
  render()
  await flushPromises()
  expect(get).toHaveBeenCalledWith(
    '/bookings/mine',
    expect.objectContaining({ params: { page: 1, size: 10 } }),
  )
  await wrapper!.get('[aria-label="Next page"]').trigger('click')
  await flushPromises()
  const update = event(2, 3)
  update.booking_key = 'CW9999999-YUL-2610'
  update.display_key = 'CW 9999999-YUL-2610'
  const before = get.mock.calls.length
  useBookingsStore().observe(update)
  await flushPromises()
  expect(wrapper!.get('.new-items-banner').text()).toContain('1 new update(s)')
  expect(get.mock.calls.slice(before).some(([url]) => url === '/bookings/lookup')).toBe(false)
})
it('removes a taken-over row and switches to the private stale endpoint', async () => {
  vi.spyOn(api, 'get').mockImplementation(async (url, config) => ({
    data: {
      items: url === '/bookings/stale' ? [] : [item()],
      total: url === '/bookings/stale' ? 0 : 1,
      page: 1,
      size: (config?.params as { size?: number } | undefined)?.size,
    },
  }))
  render()
  await flushPromises()
  useBookingsStore().observe(event())
  await flushPromises()
  expect(wrapper!.findAll('.mine-booking')).toHaveLength(0)
  expect(wrapper!.text()).toContain('A booking moved to Other.')
  await wrapper!.get('.stale-chip').trigger('click')
  await flushPromises()
  expect(api.get).toHaveBeenCalledWith(
    '/bookings/stale',
    expect.objectContaining({ params: { scope: 'mine', page: 1, size: 10 } }),
  )
})
it('replays an update that arrived during the initial list request', async () => {
  let finish!: (value: unknown) => void
  vi.spyOn(api, 'get').mockImplementation((url) =>
    url === '/bookings/mine'
      ? new Promise((done) => {
          finish = done
        })
      : Promise.resolve({ data: { items: [], total: 0, page: 1, size: 1 } }),
  )
  render()
  await flushPromises()
  useBookingsStore().observe(event())
  finish({ data: { items: [item()], total: 1, page: 1, size: 10 } })
  await flushPromises()
  expect(wrapper!.findAll('.mine-booking')).toHaveLength(0)
})
it('hydrates an own update to the top and does not duplicate a row', async () => {
  const next = lookup(2)
  next.snapshot!.last_note_preview = 'New preview'
  vi.spyOn(api, 'get').mockImplementation(async (url) => ({
    data:
      url === '/bookings/lookup'
        ? next
        : {
            items: url === '/bookings/mine' ? [item()] : [],
            total: url === '/bookings/mine' ? 1 : 0,
            page: 1,
            size: 10,
          },
  }))
  render()
  await flushPromises()
  useBookingsStore().observe(event(2, 3))
  await flushPromises()
  expect(wrapper!.findAll('.mine-booking')).toHaveLength(1)
  expect(wrapper!.get('.mine-booking').text()).toContain('New preview')
  await wrapper!.get('.mine-booking').trigger('click')
  expect(wrapper!.emitted('open')?.[0]).toEqual([KEY])
})

it('never re-inserts an older own snapshot after a later takeover removed it', async () => {
  let finish!: (value: unknown) => void
  vi.spyOn(api, 'get').mockImplementation((url) =>
    url === '/bookings/lookup'
      ? new Promise((done) => {
          finish = done
        })
      : Promise.resolve({ data: { items: [], total: 0, page: 1, size: 10 } }),
  )
  render()
  await flushPromises()
  useBookingsStore().observe(event(2, 3))
  await flushPromises()
  useBookingsStore().observe(event(3, 5))
  await flushPromises()
  finish({ data: lookup(2) })
  await flushPromises()
  expect(wrapper!.findAll('.mine-booking')).toHaveLength(0)
})
