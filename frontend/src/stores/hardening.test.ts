import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { api } from '../api/client'
import { buildCsp } from '../config/csp'
import { useAuthStore } from './auth'
import { createAppRouter } from '../router'
import type { PublicUser } from '../types/api.generated'
const key = 'booking.access_token'
const user: PublicUser = {
  id: 3,
  username: 'agent',
  full_name: 'Agent',
  role: 'agent',
  is_active: true,
  settings: {},
  must_change_password: false,
}
const token = (seconds: number) =>
  `header.${btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + seconds }))}.signature`
beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  setActivePinia(createPinia())
})
afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
})
it('expires the shared token and private identity at JWT exp without waiting for an API call', async () => {
  vi.useFakeTimers()
  const jwt = token(2)
  vi.spyOn(api, 'post').mockResolvedValue({
    data: { user, access_token: jwt, token_type: 'bearer', expires_in: 2 },
  })
  const auth = useAuthStore()
  await auth.login({ username: 'agent', password: 'Password-123' })
  expect(auth.isAuthenticated).toBe(true)
  await vi.advanceTimersByTimeAsync(2001)
  expect(auth.token).toBeNull()
  expect(auth.user).toBeNull()
  expect(localStorage.getItem(key)).toBeNull()
})
it('does not delete a newer login token when a delayed old session expires', () => {
  const auth = useAuthStore()
  auth.token = 'old-token'
  auth.user = user
  localStorage.setItem(key, 'new-token')
  auth.expire()
  expect(localStorage.getItem(key)).toBe('new-token')
  expect(auth.user).toBeNull()
})
it('restores a shared token after a storage event and clears identity on another tab logout', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue({ data: user }),
    auth = useAuthStore(),
    after = vi.fn()
  const stop = auth.syncStorage(after)
  localStorage.setItem(key, 'other-tab-token')
  window.dispatchEvent(new StorageEvent('storage', { key, newValue: 'other-tab-token' }))
  await vi.waitFor(() => expect(auth.user?.id).toBe(3))
  expect(get).toHaveBeenCalledTimes(1)
  expect(after).toHaveBeenCalledTimes(1)
  localStorage.removeItem(key)
  window.dispatchEvent(new StorageEvent('storage', { key, newValue: null }))
  expect(auth.user).toBeNull()
  expect(auth.token).toBeNull()
  stop()
})
it('restricts all workspace routes to the mandatory password page until rotation', async () => {
  const pinia = createPinia(),
    auth = useAuthStore(pinia)
  auth.token = 'test-token'
  auth.user = { ...user, must_change_password: true }
  auth.ready = true
  const router = createAppRouter(pinia, createMemoryHistory())
  for (const path of ['/', '/profile', '/summary', '/reports', '/login']) {
    await router.push(path)
    expect(router.currentRoute.value.name).toBe('change-password')
  }
  auth.user = { ...user, must_change_password: false }
  await router.push({ path: '/change-password', force: true })
  expect(router.currentRoute.value.name).toBe('home')
  auth.expire()
})
it('CSP permits only configured API and WebSocket origins and blocks executable inline content', () => {
  const csp = buildCsp('https://api.example.com/api/v1', 'wss://api.example.com/api/v1/ws')
  expect(csp).toContain("connect-src 'self' https://api.example.com wss://api.example.com")
  expect(csp).toContain("script-src 'self';")
  expect(csp).toContain("frame-ancestors 'none'")
  expect(csp).not.toContain('unsafe-eval')
  expect(csp).not.toContain('*')
  expect(() => buildCsp('http://api.example.com', 'ws://api.example.com')).toThrow()
  expect(() =>
    buildCsp('https://user:password@api.example.com', 'wss://api.example.com'),
  ).toThrow()
})

it('clears this tab when another tab clears all shared storage', () => {
  const auth = useAuthStore()
  auth.token = 'current-token'
  auth.user = user
  const stop = auth.syncStorage(() => {})
  localStorage.clear()
  window.dispatchEvent(new StorageEvent('storage', { key: null, newValue: null }))
  expect(auth.user).toBeNull()
  expect(auth.token).toBeNull()
  stop()
})
