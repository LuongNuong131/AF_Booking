import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api/client'
import { useBookingsStore } from './bookings'
import { event, KEY, lookup, statuses } from '../test/bookingFixtures'
const context = () => ({
  signal: new AbortController().signal,
  timeoutMs: 8000,
})
beforeEach(() => {
  setActivePinia(createPinia())
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})
it('caches short reads, copies results, and invalidates after updates and logout', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue({ data: lookup() })
  const store = useBookingsStore()
  const result = await store.lookup(context(), KEY)
  result.snapshot!.supplier.name = 'Local edit'
  expect((await store.lookup(context(), KEY)).snapshot?.supplier.name).toBe('Example Hotel')
  expect(get).toHaveBeenCalledTimes(1)
  store.observe(event())
  await store.lookup(context(), KEY)
  expect(get).toHaveBeenCalledTimes(2)
  store.reset()
  await store.lookup(context(), KEY)
  expect(get).toHaveBeenCalledTimes(3)
})
it('does not cache a result that started before an invalidation or session reset', async () => {
  let finish!: (result: unknown) => void
  const get = vi
    .spyOn(api, 'get')
    .mockImplementationOnce(
      () =>
        new Promise((done) => {
          finish = done
        }),
    )
    .mockResolvedValue({ data: lookup(2) })
  const store = useBookingsStore(),
    pending = store.lookup(context(), KEY)
  store.observe(event())
  finish({ data: lookup() })
  await pending
  expect((await store.lookup(context(), KEY)).version).toBe(2)
  expect(get).toHaveBeenCalledTimes(2)
})
it('allows a catalogue response across booking updates, but never across account resets', async () => {
  let finish!: (result: unknown) => void
  vi.spyOn(api, 'get').mockImplementation(
    () =>
      new Promise((done) => {
        finish = done
      }),
  )
  const store = useBookingsStore(),
    first = store.catalogue(context())
  store.observe(event())
  finish({ data: statuses })
  await first
  expect(store.statuses).toHaveLength(statuses.length)
  store.reset()
  const second = store.catalogue(context())
  store.reset()
  finish({ data: statuses })
  await second
  expect(store.statuses).toEqual([])
})
