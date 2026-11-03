import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api/client'
import { useFoldersStore } from './folders'
import { useAuthStore } from './auth'
import { useBookingsStore } from './bookings'
import { user, statuses } from '../test/bookingFixtures'
import { CW, folderDetail, folderResult, folderEvent } from '../test/folderFixtures'
const ctx = () => ({ signal: new AbortController().signal, timeoutMs: 8000 })
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-11-03T08:00:00Z'))
  setActivePinia(createPinia())
  localStorage.clear()
  useAuthStore().user = user
  useBookingsStore().statuses = statuses
})
afterEach(() => {
  useFoldersStore().reset()
  vi.restoreAllMocks()
  vi.useRealTimers()
})
it('uses a shared 50-entry LRU for search and folders and revalidates stale results', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue({ data: folderResult() }),
    store = useFoldersStore()
  await store.readSearch(ctx(), CW)
  await store.readDetail(ctx(), CW)
  expect(get).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(30001)
  expect(store.detail(CW)?.months).toHaveLength(3)
  get.mockResolvedValue({ data: folderDetail() })
  await store.readDetail(ctx(), CW)
  expect(get).toHaveBeenCalledTimes(2)
  get.mockImplementation(async (_url, config) => ({
    data: { kind: 'none', query: (config?.params as { q?: string } | undefined)?.q, items: [] },
  }))
  for (let i = 0; i < 51; i++) await store.readSearch(ctx(), `supplier ${i}`)
  expect(store.cache.size).toBe(50)
  expect(store.search('supplier 0')).toBeNull()
  await store.readSearch(ctx(), 'supplier 1')
  await store.readSearch(ctx(), 'supplier 51')
  expect(store.search('supplier 1')).not.toBeNull()
  expect(store.search('supplier 2')).toBeNull()
})
it('patches displayed months immediately and fetches only the changed folder for counts', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue({ data: folderResult() }),
    store = useFoldersStore()
  await store.readSearch(ctx(), CW)
  const stop = store.watchFolder(CW)
  const updated = folderDetail()
  updated.folder.open_count = 1
  updated.folder.stale_count = 0
  updated.folder.last_activity_at = folderEvent().updated_at
  get.mockResolvedValue({ data: updated })
  store.observe(folderEvent())
  expect(store.detail(CW)?.months[0]?.is_done).toBe(true)
  expect(store.detail(CW)?.folder.open_count).toBe(1)
  await vi.advanceTimersByTimeAsync(250)
  expect(get.mock.calls.map((c) => c[0])).toEqual(['/search', `/folders/${CW}`])
  stop()
})
it('does not retain a late response or private recent folders across sessions', async () => {
  let finish!: (r: unknown) => void
  vi.spyOn(api, 'get').mockImplementation(
    () =>
      new Promise((done) => {
        finish = done
      }),
  )
  const store = useFoldersStore()
  store.reset(3)
  const reading = store.readSearch(ctx(), CW).catch(() => {})
  store.reset(5)
  finish({ data: folderResult() })
  await reading
  expect(store.cache.size).toBe(0)
  expect(store.recent).toEqual([])
})
it('updates supplier text immediately and invalidates search after an allowed edit', async () => {
  vi.spyOn(api, 'get').mockResolvedValue({ data: folderResult() })
  const store = useFoldersStore()
  store.reset(3)
  await store.readSearch(ctx(), CW)
  store.remember(CW)
  vi.spyOn(api, 'patch').mockResolvedValue({
    data: {
      cw_number: CW,
      station_code: 'YUL',
      supplier_name: 'Renamed Supplier',
      supplier_type: 'transportation',
    },
  })
  await store.rename(ctx(), CW, {
    supplier_name: 'Renamed Supplier',
    supplier_type: 'transportation',
  })
  expect(store.detail(CW)?.folder.supplier_name).toBe('Renamed Supplier')
  expect(store.recent[0]?.supplier_type).toBe('transportation')
  expect(store.cache.values().next().value?.at).toBe(0)
})
