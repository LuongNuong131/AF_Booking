import { afterEach, expect, it, vi } from 'vitest'
import { AxiosError, type AxiosAdapter } from 'axios'
import { api } from './client'
import { configureApiSession } from './session'

const original = api.defaults.adapter
afterEach(() => {
  api.defaults.adapter = original
})
it('injects bearer tokens and handles current-session 401/403 only', async () => {
  const identity = { token: 'current-test-token', epoch: 1 }
  const unauthorized = vi.fn(),
    forbidden = vi.fn()
  const stop = configureApiSession({
    identity: () => ({ ...identity }),
    unauthorized,
    forbidden,
  })
  api.defaults.adapter = (async (config) => {
    expect(config.headers.get('Authorization')).toBe(
      config.skipAuth ? undefined : 'Bearer current-test-token',
    )
    const status = config.url === '/forbidden' ? 403 : 401
    throw new AxiosError('Test', 'ERR_BAD_RESPONSE', config, undefined, {
      config,
      status,
      statusText: '',
      headers: {},
      data: { code: 'SESSION_REPLACED', message: 'Replaced' },
    })
  }) satisfies AxiosAdapter
  await api.get('/auth/me').catch(() => {})
  expect(unauthorized).toHaveBeenCalledWith('SESSION_REPLACED')
  await api.get('/forbidden').catch(() => {})
  expect(forbidden).toHaveBeenCalledTimes(1)
  await api.post('/auth/login', {}, { skipAuth: true }).catch(() => {})
  expect(unauthorized).toHaveBeenCalledTimes(1)
  stop()
})
it('ignores a delayed 401 from a previous session, even if its token string was reused', async () => {
  const identity = { token: 'test-token', epoch: 1 },
    unauthorized = vi.fn()
  const stop = configureApiSession({
    identity: () => ({ ...identity }),
    unauthorized,
    forbidden: vi.fn(),
  })
  let reject!: (reason: unknown) => void
  api.defaults.adapter = (config) =>
    new Promise((_resolve, fail) => {
      reject = () =>
        fail(
          new AxiosError('Test', '', config, undefined, {
            config,
            status: 401,
            statusText: '',
            headers: {},
            data: { code: 'SESSION_REPLACED', message: '' },
          }),
        )
    })
  const run = api.get('/auth/me').catch(() => {})
  await vi.waitFor(() => expect(reject).toBeTypeOf('function'))
  identity.epoch++
  reject(null)
  await run
  expect(unauthorized).not.toHaveBeenCalled()
  stop()
})
