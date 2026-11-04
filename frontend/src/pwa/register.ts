import type { Pinia } from 'pinia'
import { usePwaStore } from '../stores/pwa'
export function installPwa(pinia: Pinia) {
  if (!import.meta.env.PROD || !('serviceWorker' in navigator)) return () => {}
  const store = usePwaStore(pinia)
  let stopped = false,
    interval: ReturnType<typeof setInterval> | undefined
  let controlled = !!navigator.serviceWorker.controller
  const changed = () => {
    if (store.reloading) window.location.reload()
    else if (controlled) {
      store.controllerChanged = true
      store.updateReady = true
    }
    controlled = true
  }
  navigator.serviceWorker.addEventListener('controllerchange', changed)
  async function start() {
    try {
      const registration = await navigator.serviceWorker.register('/sw.js', {
        scope: '/',
        updateViaCache: 'none',
      })
      if (stopped) return
      store.registration = registration
      if (registration.waiting && navigator.serviceWorker.controller) store.updateReady = true
      registration.addEventListener('updatefound', () => {
        const worker = registration.installing
        worker?.addEventListener('statechange', () => {
          if (worker.state === 'installed' && navigator.serviceWorker.controller)
            store.updateReady = true
        })
      })
      interval = setInterval(() => {
        if (!document.hidden) void registration.update().catch(() => {})
      }, 60000)
    } catch {
      /* Background capabilities remain unavailable; REST and outbox still work. */
    }
  }
  void start()
  return () => {
    stopped = true
    clearInterval(interval)
    navigator.serviceWorker.removeEventListener('controllerchange', changed)
  }
}
