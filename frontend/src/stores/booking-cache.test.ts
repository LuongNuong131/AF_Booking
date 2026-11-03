import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api/client'
import { useBookingsStore } from './bookings'
import { KEY, event, lookup, statuses } from '../test/bookingFixtures'
const ctx = () => ({ signal: new AbortController().signal, timeoutMs: 8000 })
beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})
it('shows SWR data immediately, patches only newer versions and refreshes stale history', async () => {
  const store = useBookingsStore()
  store.statuses = statuses
  const get = vi
    .spyOn(api, 'get')
    .mockResolvedValueOnce({ data: lookup() })
    .mockResolvedValueOnce({ data: lookup(3) })
  await store.lookup(ctx(), KEY)
  store.observe(event(2))
  expect(store.peekLookup(KEY)?.data.snapshot?.version).toBe(2)
  expect(store.peekLookup(KEY)?.fetchedAt).toBe(0)
  store.observe(event(1))
  expect(store.peekLookup(KEY)?.data.snapshot?.version).toBe(2)
  await store.lookup(ctx(), KEY)
  expect(store.peekLookup(KEY)?.data.snapshot?.version).toBe(3)
  expect(get).toHaveBeenCalledTimes(2)
})
it('shares an in-flight lookup and keeps at most 50 cache entries', async () => {
  const store = useBookingsStore(),
    get = vi.spyOn(api, 'get').mockResolvedValue({ data: lookup() })
  await Promise.all([store.lookup(ctx(), KEY), store.lookup(ctx(), KEY)])
  expect(get).toHaveBeenCalledTimes(1)
  for (let i = 0; i < 51; i++) await store.lookup(ctx(), `CW${1000000 + i}-RDU-2609`)
  expect(store.peekLookup(KEY)).toBeNull()
})
it('persists a status catalogue ETag and accepts 304 without losing items', async () => {
  const store = useBookingsStore(),
    get = vi
      .spyOn(api, 'get')
      .mockResolvedValueOnce({ status: 200, headers: { etag: '"status-v1"' }, data: statuses })
      .mockResolvedValueOnce({ status: 304, headers: { etag: '"status-v1"' } })
  await store.catalogue(ctx())
  store.invalidateCatalogue()
  await store.catalogue(ctx(), true)
  expect(get.mock.calls[1]?.[1]?.headers).toEqual({ 'If-None-Match': '"status-v1"' })
  expect(store.statuses).toEqual(statuses)
})
