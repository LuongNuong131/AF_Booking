import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'
import { effectScope } from 'vue'
import { useRequest } from './useRequest'

function failure(method = 'get', status?: number, retryAfter?: string) {
  const config = {
    method,
    headers: new AxiosHeaders(),
  } as InternalAxiosRequestConfig
  return new AxiosError(
    'Test failure',
    status ? 'ERR_BAD_RESPONSE' : 'ERR_NETWORK',
    config,
    undefined,
    status
      ? {
          status,
          statusText: '',
          config,
          headers: { 'retry-after': retryAfter },
          data: { code: 'SERVICE_BUSY', message: 'Busy' },
        }
      : undefined,
  )
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
beforeEach(() => {
  vi.useFakeTimers()
  vi.spyOn(Math, 'random').mockReturnValue(0)
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useRequest bounded lifecycle', () => {
  it('becomes slow and times out even if the transport ignores abort; ignores late data', async () => {
    const deferredResult = deferred<string>()
    const request = useRequest(() => deferredResult.promise, {
      timeoutMs: 8000,
      slowMs: 3000,
    })
    const run = request.run()
    await vi.advanceTimersByTimeAsync(3000)
    expect(request.state.value).toBe('slow')
    await vi.advanceTimersByTimeAsync(5000)
    expect(await run).toBeUndefined()
    expect(request.state.value).toBe('timeout')
    expect(request.pending.value).toBe(false)
    deferredResult.resolve('late')
    await Promise.resolve()
    expect(request.data.value).toBeUndefined()
    expect(vi.getTimerCount()).toBe(0)
  })
  it('cancels the previous request and accepts only the newest result', async () => {
    const first = deferred<string>(),
      second = deferred<string>()
    const signals: AbortSignal[] = []
    const fn = vi.fn(({ signal }: { signal: AbortSignal }) => {
      signals.push(signal)
      return signals.length === 1 ? first.promise : second.promise
    })
    const request = useRequest(fn, { timeoutMs: 8000 })
    const older = request.run()
    await Promise.resolve()
    const newer = request.run()
    await Promise.resolve()
    expect(signals[0]?.aborted).toBe(true)
    second.resolve('new')
    expect(await newer).toBe('new')
    first.resolve('old')
    await older
    expect(request.data.value).toBe('new')
    expect(request.state.value).toBe('success')
  })
  it('cancels manually and when its Vue scope is disposed', async () => {
    const scope = effectScope()
    const request = scope.run(() =>
      useRequest(() => new Promise<never>(() => {}), { timeoutMs: 1000 }),
    )!
    const run = request.run()
    await Promise.resolve()
    scope.stop()
    await run
    expect(request.state.value).toBe('idle')
    expect(request.pending.value).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
  })
  it.each([undefined, 503, 504])('retries a GET once for network/status %s', async (status) => {
    const fn = vi.fn().mockRejectedValueOnce(failure('get', status)).mockResolvedValue('ok')
    const request = useRequest(fn, { timeoutMs: 8000, retry: true })
    const run = request.run()
    await vi.advanceTimersByTimeAsync(299)
    expect(fn).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(await run).toBe('ok')
    expect(fn).toHaveBeenCalledTimes(2)
    expect(fn.mock.calls[1]?.[0].timeoutMs).toBe(7700)
  })
  it('respects Retry-After and keeps one total deadline', async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(failure('get', 503, '2'))
      .mockImplementation(() => new Promise<never>(() => {}))
    const request = useRequest(fn, { timeoutMs: 5000, retry: true })
    const run = request.run()
    await vi.advanceTimersByTimeAsync(1999)
    expect(fn).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(fn).toHaveBeenCalledTimes(2)
    expect(fn.mock.calls[1]?.[0].timeoutMs).toBe(3000)
    await vi.advanceTimersByTimeAsync(3000)
    await run
    expect(request.state.value).toBe('timeout')
  })
  it('does not wait beyond its budget for Retry-After', async () => {
    const fn = vi.fn().mockRejectedValue(failure('get', 503, '60'))
    const request = useRequest(fn, { timeoutMs: 1000, retry: true })
    await request.run()
    expect(fn).toHaveBeenCalledTimes(1)
    expect(request.state.value).toBe('error')
    expect(vi.getTimerCount()).toBe(0)
  })
  it.each(['post', 'patch', 'delete', 'put'])('never automatically retries %s', async (method) => {
    const fn = vi.fn().mockRejectedValue(failure(method, 503))
    const request = useRequest(fn, { timeoutMs: 8000, retry: true })
    await request.run()
    expect(fn).toHaveBeenCalledTimes(1)
    expect(request.pending.value).toBe(false)
  })
  it('stops after two GET attempts and never retries validation failures', async () => {
    const fn = vi.fn().mockRejectedValue(failure('get', 503))
    const request = useRequest(fn, { timeoutMs: 8000, retry: true })
    const run = request.run()
    await vi.advanceTimersByTimeAsync(300)
    await run
    expect(fn).toHaveBeenCalledTimes(2)
    const invalid = vi.fn().mockRejectedValue(failure('get', 422))
    await useRequest(invalid, { timeoutMs: 8000, retry: true }).run()
    expect(invalid).toHaveBeenCalledTimes(1)
  })
})
