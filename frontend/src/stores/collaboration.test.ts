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
it('follows folders independently of booking subscriptions and keeps state on failure', async () => {
  const send = vi.spyOn(api, 'request').mockResolvedValue({ data: { following: true } })
  const store = useCollaborationStore()
  store.seed(KEY, true)
  expect(await store.folderFollow('CW2154654-RDU', true)).toBe(true)
  expect(send).toHaveBeenCalledWith(expect.objectContaining({ url: '/folders/CW2154654-RDU/follow', method: 'PUT' }))
  expect(store.followingFolders['CW2154654-RDU']).toBe(true)
  expect(store.watched[KEY]).toBe(true)
  send.mockRejectedValueOnce({ isAxiosError: true, response: { status: 503, data: { code: 'SERVICE_BUSY' } } })
  expect(await store.folderFollow('CW2154654-RDU', false)).toBe(false)
  expect(store.followingFolders['CW2154654-RDU']).toBe(true)
  store.reset()
  expect(store.followingFolders).toEqual({})
  expect(store.folderPending).toEqual([])
})
it('blocks duplicate folder requests and discards replies from a replaced session', async () => {
  let reply!: (value: unknown) => void
  const send = vi.spyOn(api, 'request').mockReturnValue(new Promise(resolve => { reply = resolve }) as ReturnType<typeof api.request>)
  const store = useCollaborationStore()
  const first = store.folderFollow('CW2154654-RDU', true)
  expect(await store.folderFollow('CW2154654-RDU', true)).toBe(false)
  useAuthStore().epoch++
  store.reset()
  reply({ data: { following: true } })
  await first
  expect(send).toHaveBeenCalledOnce()
  expect(store.followingFolders).toEqual({})
})
