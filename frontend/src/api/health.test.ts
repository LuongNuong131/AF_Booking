import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'
import { checkServices } from './health'

vi.mock('./client', () => ({ api: { get: vi.fn() } }))

describe('service readiness', () => {
  beforeEach(() => vi.resetAllMocks())
  it('reports a connected database from a successful probe', async () => {
    vi.mocked(api.get).mockResolvedValue({
      status: 200,
      data: { status: 'ok', database: 'connected' },
    })
    expect(await checkServices()).toEqual({
      api: 'online',
      database: 'connected',
    })
  })
  it('distinguishes an unconfigured database from an unreachable API', async () => {
    vi.mocked(api.get).mockResolvedValue({
      status: 503,
      data: {
        code: 'SERVICE_BUSY',
        message: 'The server is busy.',
        details: { database: 'not_configured' },
      },
    })
    expect(await checkServices()).toEqual({
      api: 'online',
      database: 'not_configured',
    })
    vi.mocked(api.get).mockRejectedValue(new Error('timeout'))
    expect(await checkServices()).toEqual({
      api: 'offline',
      database: 'unavailable',
    })
  })
  it('recognizes a database failure without treating it as a network failure', async () => {
    vi.mocked(api.get).mockResolvedValue({
      status: 503,
      data: {
        code: 'SERVICE_BUSY',
        message: 'The server is busy.',
        details: { database: 'unavailable' },
      },
    })
    expect(await checkServices()).toEqual({
      api: 'online',
      database: 'unavailable',
    })
  })
  it('rejects the old readiness error format', async () => {
    vi.mocked(api.get).mockResolvedValue({
      status: 503,
      data: { database: 'not_configured' },
    })
    expect(await checkServices()).toEqual({
      api: 'offline',
      database: 'unavailable',
    })
  })
  it('does not accept an unrelated HTML or JSON response as readiness', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: '<html>Fallback page</html>',
    })
    expect(await checkServices()).toEqual({
      api: 'offline',
      database: 'unavailable',
    })
  })
})
