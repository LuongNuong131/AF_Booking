/* Build replaces these two constants; no API/auth response is ever cached. */
const PRECACHE = __PRECACHE__
const CACHE = 'booking-static-' + __BUILD_ID__
const STATIC = new Set(PRECACHE)
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) =>
        cache.addAll(
          PRECACHE.map((url) => new Request(url, { credentials: 'omit', cache: 'reload' })),
        ),
      ),
  )
})
self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      for (const name of await caches.keys())
        if (name.startsWith('booking-static-') && name !== CACHE) await caches.delete(name)
      await self.clients.claim()
    })(),
  )
})
self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting()
})
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  if (
    event.request.method !== 'GET' ||
    url.origin !== self.location.origin ||
    url.pathname.startsWith('/api/')
  )
    return
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(async () => (await caches.open(CACHE)).match('/index.html')),
    )
  } else if (!url.search && STATIC.has(url.pathname)) {
    event.respondWith(
      caches
        .open(CACHE)
        .then(async (cache) => (await cache.match(url.pathname)) || fetch(event.request)),
    )
  }
})
const canonical = (value) =>
  typeof value === 'string' && /^CW[0-9]{5,10}-[A-Z]{3}-[0-9]{2}(?:0[1-9]|1[0-2])$/.test(value)
self.addEventListener('push', (event) => {
  let data
  try {
    data = event.data.json()
  } catch {
    return
  }
  if (!canonical(data?.booking_key)) return
  const allowed = new Set(['Task due', 'Booking assigned', 'Booking updated'])
  const title = allowed.has(data.title) ? data.title : 'Booking update'
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.booking_key.replace(/^CW/, 'CW '),
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-192.png',
      tag: `${title}:${data.booking_key}`,
      renotify: false,
      data: { booking_key: data.booking_key },
    }),
  )
})
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const key = event.notification.data?.booking_key
  if (!canonical(key)) return
  const target = new URL('/summary/' + encodeURIComponent(key), self.location.origin).href
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const client of windows)
        if (new URL(client.url).origin === self.location.origin) {
          await client.navigate(target)
          return client.focus()
        }
      return self.clients.openWindow(target)
    })(),
  )
})
