import { expect, it } from 'vitest'
import { resolveEndpoints } from './api-url'
it('uses VITE_API_URL before the legacy alias and derives the matching WebSocket endpoint', () => {
  expect(
    resolveEndpoints(
      {
        VITE_API_URL: 'https://primary.example/api/v1',
        VITE_API_BASE_URL: 'https://old.example/api/v1',
      },
      true,
    ),
  ).toEqual({
    apiUrl: 'https://primary.example/api/v1',
    wsUrl: 'wss://primary.example/api/v1/ws',
  })
  expect(resolveEndpoints({ VITE_API_BASE_URL: 'https://old.example/api/v1' }, true).apiUrl).toBe(
    'https://old.example/api/v1',
  )
})
it.each([
  'ws://api.example/api/v1/ws',
  'wss://user:secret@api.example/api/v1/ws',
  'wss://api.example/api/v1/ws?token=secret',
  'wss://api.example/ws',
])('rejects unsafe/mismatched production WS configuration', (url) => {
  expect(() =>
    resolveEndpoints({ VITE_API_URL: 'https://api.example/api/v1', VITE_WS_URL: url }, true),
  ).toThrow()
})
