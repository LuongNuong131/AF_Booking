import { ref, onScopeDispose } from 'vue'
import { api } from '../api/client'
import { timeouts } from '../config/timeouts'

export function useWarmup() {
  const state = ref<'waking' | 'ready' | 'unavailable'>('waking')
  let stopped = false,
    timer: ReturnType<typeof setTimeout> | undefined
  const controller = new AbortController()
  async function run(attempt = 0) {
    try {
      await api.get('/health/warm', {
        skipAuth: true,
        signal: controller.signal,
        timeout: timeouts.warmup,
      })
      if (!stopped) state.value = 'ready'
    } catch {
      if (stopped) return
      if (attempt < 5) timer = setTimeout(() => void run(attempt + 1), 5000)
      else state.value = 'unavailable'
    }
  }
  void run()
  onScopeDispose(() => {
    stopped = true
    clearTimeout(timer)
    controller.abort()
  })
  return { state }
}
