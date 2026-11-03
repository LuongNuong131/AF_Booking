import { afterEach, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { api } from '../api/client'
import { useWarmup } from './useWarmup'
afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})
it('starts without blocking login, retries at 5s and stops after six attempts', async () => {
  vi.useFakeTimers()
  const get = vi.spyOn(api, 'get').mockRejectedValue(new Error('sleeping'))
  const scope = effectScope(),
    warm = scope.run(() => useWarmup())!
  await vi.advanceTimersByTimeAsync(25000)
  expect(get).toHaveBeenCalledTimes(6)
  expect(warm.state.value).toBe('unavailable')
  await vi.advanceTimersByTimeAsync(10000)
  expect(get).toHaveBeenCalledTimes(6)
  scope.stop()
})
it('cancels a warmup on route disposal and clears retry timers', async () => {
  vi.useFakeTimers()
  let signal!: AbortSignal
  const get = vi.spyOn(api, 'get').mockImplementation((_, config) => {
    signal = config!.signal as AbortSignal
    return new Promise(() => {})
  })
  const scope = effectScope()
  scope.run(() => useWarmup())
  scope.stop()
  expect(signal.aborted).toBe(true)
  await vi.advanceTimersByTimeAsync(100000)
  expect(get).toHaveBeenCalledTimes(1)
})
