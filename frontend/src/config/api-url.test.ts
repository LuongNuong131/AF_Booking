import { describe, expect, it } from 'vitest'
import { resolveApiBaseUrl } from './api-url'

describe('deployment URL validation', () => {
  it('allows localhost only for development', () => {
    expect(resolveApiBaseUrl(undefined, false)).toBe('http://localhost:8000/api/v1')
    expect(() => resolveApiBaseUrl(undefined, true)).toThrow()
    expect(() => resolveApiBaseUrl('http://localhost:8000/api/v1', true)).toThrow()
  })
  it('accepts the HTTPS backend URL and normalizes its trailing slash', () => {
    expect(resolveApiBaseUrl('https://tracker.onrender.com/api/v1/', true))
      .toBe('https://tracker.onrender.com/api/v1')
  })
  it.each([
    'https://example.com',
    'https://user:secret@example.com/api/v1',
    'https://example.com/api/v1?token=secret',
    'https://example.com/api/v1#fragment',
    'ftp://example.com/api/v1',
  ])('rejects invalid configuration: %s', (url) => {
    expect(() => resolveApiBaseUrl(url, true)).toThrow()
  })
})
