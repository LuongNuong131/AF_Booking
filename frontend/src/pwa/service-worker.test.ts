import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { runInNewContext } from 'node:vm'
import { it, expect, vi } from 'vitest'
const source = readFileSync(resolve('src/pwa/service-worker.js'), 'utf8')
  .replace('__PRECACHE__', JSON.stringify(['/index.html', '/assets/app.js']))
  .replace('__BUILD_ID__', '"test-build"')
function rig() {
  const handlers = new Map<string, (event: any) => unknown>(),
    showNotification = vi.fn().mockResolvedValue(undefined),
    openWindow = vi.fn().mockResolvedValue(undefined),
    caches = {
      open: vi.fn().mockResolvedValue({ match: vi.fn() }),
      keys: vi.fn().mockResolvedValue([]),
      delete: vi.fn(),
    }
  const self = {
    location: { origin: 'https://app.example' },
    registration: { showNotification },
    clients: { matchAll: vi.fn().mockResolvedValue([]), openWindow, claim: vi.fn() },
    addEventListener: (name: string, handler: (event: any) => unknown) =>
      handlers.set(name, handler),
    skipWaiting: vi.fn(),
  }
  runInNewContext(source, { self, caches, URL, Request, fetch: vi.fn() })
  return { handlers, self, caches, showNotification, openWindow }
}
it('never handles API, cross-origin, mutation or non-static requests with the cache', () => {
  const { handlers, caches } = rig()
  for (const request of [
    { url: 'https://app.example/api/v1/auth/me', method: 'GET', mode: 'cors' },
    { url: 'https://api.example/api/v1/bookings', method: 'GET', mode: 'cors' },
    { url: 'https://app.example/assets/app.js', method: 'POST', mode: 'cors' },
    { url: 'https://app.example/private.json', method: 'GET', mode: 'cors' },
  ]) {
    const respondWith = vi.fn()
    handlers.get('fetch')!({ request, respondWith })
    expect(respondWith).not.toHaveBeenCalled()
  }
  expect(caches.open).not.toHaveBeenCalled()
})
it('shows only the canonical booking key and opens a same-origin validated booking route', async () => {
  const { handlers, showNotification, openWindow } = rig()
  let pending: Promise<unknown> | undefined
  handlers.get('push')!({
    data: {
      json: () => ({
        title: 'Booking assigned',
        booking_key: 'CW2154654-RDU-2609',
        body: 'secret note must be ignored',
      }),
    },
    waitUntil: (value: Promise<unknown>) => (pending = value),
  })
  await pending
  expect(showNotification).toHaveBeenCalledWith(
    'Booking assigned',
    expect.objectContaining({
      body: 'CW 2154654-RDU-2609',
      data: { booking_key: 'CW2154654-RDU-2609' },
    }),
  )
  handlers.get('notificationclick')!({
    notification: {
      close: vi.fn(),
      data: { booking_key: 'CW2154654-RDU-2609', url: 'https://evil.test' },
    },
    waitUntil: (value: Promise<unknown>) => (pending = value),
  })
  await pending
  expect(openWindow).toHaveBeenCalledWith('https://app.example/summary/CW2154654-RDU-2609')
  handlers.get('push')!({
    data: { json: () => ({ booking_key: 'https://evil.test' }) },
    waitUntil: vi.fn(),
  })
  expect(showNotification).toHaveBeenCalledTimes(1)
})
