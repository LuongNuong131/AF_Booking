import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { effectScope, reactive, type EffectScope } from 'vue'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useBookingsStore } from '../stores/bookings'
import { useFoldersStore } from '../stores/folders'
import { useBookingWorkspace } from './useBookingWorkspace'
import { useSmartSearch } from './useSmartSearch'
import { KEY, lookup, statuses, user } from '../test/bookingFixtures'
import { CW, folderResult } from '../test/folderFixtures'
let scope: EffectScope
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-11-03T08:00:00Z'))
  setActivePinia(createPinia())
  localStorage.clear()
  useAuthStore().user = user
  useBookingsStore().statuses = statuses
  scope = effectScope()
})
afterEach(() => {
  scope.stop()
  useFoldersStore().reset()
  vi.restoreAllMocks()
  vi.useRealTimers()
})
function setup() {
  return scope.run(() => {
    const w = reactive(useBookingWorkspace()),
      opened = vi.fn(),
      nav = useSmartSearch(w, opened)
    return { w, nav, opened }
  })!
}
it('debounces other queries 200 ms and restores the cached folder when going back', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue({ data: folderResult() }),
    { w, nav } = setup()
  w.input = CW
  nav.typed()
  await vi.advanceTimersByTimeAsync(199)
  expect(get).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(1)
  expect(nav.result.value?.kind).toBe('folder')
  nav.openFolder(`${CW}-YUL`)
  expect(nav.level.value).toBe('folder')
  expect(w.input).toBe('')
  nav.level.value = 'booking'
  nav.back()
  expect(nav.level.value).toBe('folder')
  expect(useFoldersStore().detail(`${CW}-YUL`)?.months).toHaveLength(3)
  nav.back()
  expect(nav.level.value).toBe('root')
  expect(w.input).toBe(CW)
  await Promise.resolve()
  expect(get).toHaveBeenCalledTimes(1)
})
it('opens full and partial keys directly, retains display text and applies one-touch resolution', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue({ data: lookup() }),
    { w, nav } = setup()
  w.input = 'cw 2154654 - rdu - 2609'
  nav.typed()
  await nav.submit()
  expect(w.input).toBe('CW 2154654-RDU-2609')
  expect(get.mock.calls[0]?.[0]).toBe('/bookings/lookup')
  expect(get.mock.calls[0]?.[1]?.params).toMatchObject({ key: KEY })
  const partial = lookup()
  partial.resolution = {
    ...partial.resolution,
    status: 'resolved_from_partial',
    input_kind: 'partial',
  }
  get.mockResolvedValue({ data: partial })
  w.input = 'CW 2154654-2609'
  nav.typed()
  await nav.submit()
  expect(w.key).toBeNull()
  await nav.submit()
  expect(w.key).toBe(KEY)
  expect(get).toHaveBeenCalledTimes(2)
})
it('cancels an old search before issuing the replacement and releases loading at eight seconds', async () => {
  const signals: AbortSignal[] = []
  vi.spyOn(api, 'get').mockImplementation((_url, config) => {
    signals.push(config!.signal as AbortSignal)
    return new Promise(() => {})
  })
  const { w, nav } = setup()
  w.input = 'double tree'
  nav.typed()
  await vi.advanceTimersByTimeAsync(200)
  await vi.advanceTimersByTimeAsync(3000)
  expect(nav.request.state.value).toBe('slow')
  w.input = 'hilton yul'
  nav.typed()
  expect(signals[0]?.aborted).toBe(true)
  await vi.advanceTimersByTimeAsync(8200)
  expect(nav.request.state.value).toBe('timeout')
  expect(nav.request.pending.value).toBe(false)
  expect(signals[1]?.aborted).toBe(true)
})
