import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { api } from '../api/client'
import { useAuthStore } from './auth'
import { useNotificationsStore } from './notifications'
import { useUiStore } from './ui'
import { createAppRouter, safeRedirect } from '../router'
import { formatDateTime } from '../utils/dateTime'
import { parseLogin } from '../api/auth-payload'
import type { PublicUser } from '../types/api.generated'

const user: PublicUser = {
  id: 3,
  username: 'agent',
  full_name: 'Test Agent',
  role: 'agent',
  is_active: true,
  settings: { timezone: 'America/Toronto' },
}
beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  setActivePinia(createPinia())
})
afterEach(() => vi.restoreAllMocks())
it('logs in using the contract, persists only the token per tab, and clears private data on expiry', async () => {
  const post = vi
    .spyOn(api, 'post')
    .mockResolvedValue({
      data: { access_token: 'test-token', user, expires_in: 3600, token_type: 'bearer' },
    })
  const auth = useAuthStore()
  expect(await auth.login({ username: 'agent', password: 'test-password' })).toBe(true)
  expect(post).toHaveBeenCalledWith(
    '/auth/login',
    { username: 'agent', password: 'test-password' },
    expect.objectContaining({ skipAuth: true, timeout: 10000 }),
  )
  expect(sessionStorage.getItem('booking.access_token')).toBe('test-token')
  expect(localStorage.getItem('booking.access_token')).toBeNull()
  expect(auth.isAuthenticated).toBe(true)
  expect(auth.timezone).toBe('America/Toronto')
  auth.expire()
  expect(auth.user).toBeNull()
  expect(auth.token).toBeNull()
  expect(auth.loginRequest.data).toBeUndefined()
  expect(sessionStorage.length).toBe(0)
})
it('restores one shared request and rejects malformed login data', async () => {
  sessionStorage.setItem('booking.access_token', 'test-token')
  const get = vi.spyOn(api, 'get').mockResolvedValue({ data: user })
  const auth = useAuthStore()
  await Promise.all([auth.ensureSession(), auth.ensureSession()])
  expect(get).toHaveBeenCalledTimes(1)
  expect(auth.user?.id).toBe(3)
  expect(() => parseLogin({ access_token: 'test', user: { ...user, role: 'owner' } })).toThrow()
})
it.each(['agent', 'qc', 'admin'] as const)(
  'guards routes for %s and canonicalizes booking URLs',
  async (role) => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.user = { ...user, role }
    auth.token = 'test-token'
    auth.ready = true
    const router = createAppRouter(pinia, createMemoryHistory())
    await router.push('/admin/users')
    expect(router.currentRoute.value.name).toBe(role === 'admin' ? 'admin' : 'home')
    await router.push('/reports')
    expect(router.currentRoute.value.name).toBe(role === 'agent' ? 'home' : 'reports')
    await router.push('/summary/CW%202154654-rdu-2609')
    expect(router.currentRoute.value.params.key).toBe('CW2154654-RDU-2609')
    await router.push('/summary/invalid')
    expect(router.currentRoute.value.name).toBe('summary')
  },
)
it('redirects a guest with a local return path, blocks unsafe return targets', async () => {
  const pinia = createPinia()
  const router = createAppRouter(pinia, createMemoryHistory())
  await router.push('/profile')
  expect(router.currentRoute.value.name).toBe('login')
  expect(router.currentRoute.value.query.redirect).toBe('/profile')
  for (const value of [
    'https://outside.example/',
    '//outside.example',
    '/\\outside.example',
    '/login',
    '/\nprofile',
  ])
    expect(safeRedirect(value)).toBe('/')
  expect(safeRedirect('/summary?status=open')).toBe('/summary?status=open')
})
it('persists explicit themes and follows system changes only in system mode', () => {
  const ui = useUiStore()
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  vi.spyOn(window, 'matchMedia').mockReturnValue(media)
  const stop = ui.startTheme()
  ui.setTheme('dark')
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(localStorage.getItem('booking.theme')).toBe('dark')
  window.dispatchEvent(new StorageEvent('storage', { key: 'booking.theme', newValue: 'light' }))
  expect(ui.resolvedTheme).toBe('light')
  stop()
})
it('does not erase a new unread notification while mark-all is in flight', async () => {
  let finish!: (value: unknown) => void
  vi.spyOn(api, 'post').mockImplementation(
    () =>
      new Promise((done) => {
        finish = done
      }),
  )
  vi.spyOn(api, 'get').mockImplementation(() => new Promise(() => {}))
  const notifications = useNotificationsStore()
  notifications.unread = 1
  const marking = notifications.markAllRead()
  await Promise.resolve()
  notifications.incoming({
    id: 42,
    booking_key: 'CW2154654-RDU-2609',
    display_key: 'CW 2154654-RDU-2609',
    type: 'taken_over',
    by_agent_name: 'Other',
    created_at: '2026-11-03T00:00:00.000Z',
  })
  finish({ data: { ok: true } })
  expect(await marking).toBe(true)
  expect(notifications.unread).toBe(2)
  notifications.reset()
  expect(notifications.unread).toBe(0)
  expect(notifications.items).toEqual([])
})
it('renders dates in the user time zone across daylight saving changes', () => {
  expect(formatDateTime('2026-11-01T05:30:00.000Z', 'America/Toronto')).toMatch(
    /^01 Nov 2026 01:30:00 GMT-4$/,
  )
  expect(formatDateTime('2026-11-01T06:30:00.000Z', 'America/Toronto')).toMatch(
    /^01 Nov 2026 01:30:00 GMT-5$/,
  )
  expect(formatDateTime('invalid', 'UTC')).toBe('')
})


it('keeps the new account mutation busy while a cancelled old account action settles', async () => {
  vi.spyOn(api, 'post').mockImplementation(() => new Promise(() => {}))
  const notifications = useNotificationsStore()
  const older = notifications.markAllRead()
  await Promise.resolve()
  notifications.reset()
  const newer = notifications.markAllRead()
  await older
  expect(notifications.markingAll).toBe(true)
  notifications.reset()
  await newer
})
