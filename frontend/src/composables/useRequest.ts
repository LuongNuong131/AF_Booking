import { computed, getCurrentScope, onScopeDispose, ref, shallowRef } from 'vue'
import { timeouts } from '../config/timeouts'
import { normalizeRequestError } from '../api/request-error'
import type { RequestFailure } from '../api/errors'

export type RequestState = 'idle' | 'loading' | 'slow' | 'timeout' | 'error' | 'success'
export interface RequestContext {
  signal: AbortSignal
  timeoutMs: number
}
export interface RequestOptions {
  timeoutMs: number
  slowMs?: number
  retry?: boolean
}
class Interrupted extends Error {
  constructor(readonly reason: 'cancel' | 'timeout') {
    super(reason)
  }
}

export function useRequest<T, Args extends unknown[] = []>(
  fn: (context: RequestContext, ...args: Args) => Promise<T>,
  options: RequestOptions,
) {
  if (!Number.isFinite(options.timeoutMs) || options.timeoutMs <= 0)
    throw new Error('A finite positive request deadline is required.')
  const data = shallowRef<T>()
  const state = ref<RequestState>('idle')
  const error = shallowRef<RequestFailure | null>(null)
  const pending = computed(() => state.value === 'loading' || state.value === 'slow')
  let sequence = 0
  let active: AbortController | null = null

  function cancel(): void {
    sequence++
    active?.abort(new Interrupted('cancel'))
    active = null
    if (pending.value) state.value = 'idle'
  }

  async function run(...args: Args): Promise<T | undefined> {
    active?.abort(new Interrupted('cancel'))
    const id = ++sequence
    const controller = new AbortController()
    active = controller
    const deadline = Date.now() + options.timeoutMs
    state.value = 'loading'
    error.value = null
    let onAbort: (() => void) | undefined
    const interrupted = new Promise<never>((_, reject) => {
      onAbort = () =>
        reject(
          controller.signal.reason instanceof Interrupted
            ? controller.signal.reason
            : new Interrupted('cancel'),
        )
      controller.signal.addEventListener('abort', onAbort, { once: true })
    })
    const slow = setTimeout(() => {
      if (id === sequence && state.value === 'loading') state.value = 'slow'
    }, options.slowMs ?? timeouts.slow)
    const timer = setTimeout(() => controller.abort(new Interrupted('timeout')), options.timeoutMs)
    try {
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const result = await Promise.race([
            Promise.resolve().then(() => {
              if (controller.signal.aborted) throw controller.signal.reason
              return fn(
                {
                  signal: controller.signal,
                  timeoutMs: Math.max(1, Math.min(options.timeoutMs, deadline - Date.now())),
                },
                ...args,
              )
            }),
            interrupted,
          ])
          if (id !== sequence || controller.signal.aborted) return undefined
          data.value = result
          state.value = 'success'
          return result
        } catch (caught) {
          if (caught instanceof Interrupted) throw caught
          if (id !== sequence) return undefined
          if (controller.signal.aborted) throw controller.signal.reason
          const failure = normalizeRequestError(caught)
          const eligible =
            options.retry &&
            attempt === 0 &&
            failure.method === 'GET' &&
            (failure.network || failure.status === 503 || failure.status === 504)
          const delay = Math.max(
            failure.retryAfterMs ?? 0,
            timeouts.retryJitter + Math.random() * timeouts.retryJitterRange,
          )
          if (!eligible || delay >= deadline - Date.now()) {
            error.value = failure
            state.value = failure.code === 'REQUEST_TIMEOUT' ? 'timeout' : 'error'
            return undefined
          }
          error.value = failure
          let backoff: ReturnType<typeof setTimeout> | undefined
          try {
            await Promise.race([
              new Promise<void>((resolve) => {
                backoff = setTimeout(resolve, delay)
              }),
              interrupted,
            ])
          } finally {
            clearTimeout(backoff)
          }
          if (id === sequence) error.value = null
        }
      }
    } catch (caught) {
      if (id !== sequence) return undefined
      if (caught instanceof Interrupted && caught.reason === 'timeout') {
        error.value = { code: 'REQUEST_TIMEOUT', message: '' }
        state.value = 'timeout'
      } else if (caught instanceof Interrupted) state.value = 'idle'
      else {
        error.value = normalizeRequestError(caught)
        state.value = 'error'
      }
    } finally {
      clearTimeout(timer)
      clearTimeout(slow)
      if (onAbort) controller.signal.removeEventListener('abort', onAbort)
      if (id === sequence) {
        active = null
        if (pending.value) state.value = 'idle'
      }
    }
    return undefined
  }
  if (getCurrentScope()) onScopeDispose(cancel)
  return { data, state, error, pending, run, cancel }
}
