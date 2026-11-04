import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api/client'
import { useAuthStore } from './auth'
import { useCollaborationStore } from './collaboration'
import { user, KEY } from '../test/bookingFixtures'
beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().user = user
})
afterEach(() => vi.restoreAllMocks())
it('reconciles a replayed private watch flag instead of undoing a later subscription', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue({ data: { snapshot: { my_watching: true } } })
  const store = useCollaborationStore()
  store.seed(KEY, true)
  await store.acceptNote(KEY, false, '2026-11-03T08:00:00.000Z', true)
  expect(get).toHaveBeenCalledOnce()
  expect(store.watched[KEY]).toBe(true)
})
it('looks up unknown watch state, sends DELETE, and updates only after acknowledgement', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue({ data: { snapshot: { my_watching: true } } }),
    send = vi.spyOn(api, 'request').mockResolvedValue({ data: { watching: false } })
  const store = useCollaborationStore()
  expect(await store.toggle(KEY)).toBe(true)
  expect(get).toHaveBeenCalledOnce()
  expect(send).toHaveBeenCalledWith(expect.objectContaining({ method: 'DELETE' }))
  expect(store.watched[KEY]).toBe(false)
})
it('deduplicates clicks and keeps previous state when the server refuses the operation', async () => {
  const send = vi.spyOn(api, 'request').mockRejectedValue({
    isAxiosError: true,
    response: {
      status: 422,
      data: { code: 'WATCH_LIMIT_REACHED', message: 'Limit' },
    },
  })
  const store = useCollaborationStore()
  store.seed(KEY, false)
  const first = store.toggle(KEY)
  expect(await store.toggle(KEY)).toBe(false)
  await first
  expect(send).toHaveBeenCalledOnce()
  expect(store.watched[KEY]).toBe(false)
  expect(store.pending).toEqual([])
})
