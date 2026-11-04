import { expect, it, vi, beforeEach } from 'vitest'
import { createApp } from 'vue'
import { init } from '@sentry/vue'
import { scrubEvent, initializeMonitoring } from './monitoring'
import { buildCsp } from './config/csp'
vi.mock('@sentry/vue', () => ({
  init: vi.fn(),
  vueIntegration: vi.fn(() => ({ name: 'Vue' })),
  globalHandlersIntegration: vi.fn(() => ({ name: 'GlobalHandlers' })),
}))
beforeEach(() => vi.clearAllMocks())
it('does not initialize reporting when the optional DSN is blank', async () => {
  expect(await initializeMonitoring(createApp({}), '')).toBe(false)
  expect(init).not.toHaveBeenCalled()
})
it('uses explicit privacy limits and allows only the configured Sentry origin in CSP', async () => {
  const dsn = 'https://public@sentry.example/42'
  expect(await initializeMonitoring(createApp({}), dsn)).toBe(true)
  expect(init).toHaveBeenCalledWith(
    expect.objectContaining({
      attachProps: false,
      defaultIntegrations: false,
      dataCollection: {
        userInfo: false,
        cookies: false,
        httpHeaders: false,
        httpBodies: [],
        urlQueryParams: false,
      },
      beforeSend: scrubEvent,
    }),
  )
  expect(buildCsp('https://api.example/api/v1', 'wss://api.example/api/v1/ws', dsn)).toContain(
    'https://sentry.example',
  )
  expect(() =>
    buildCsp(
      'https://api.example/api/v1',
      'wss://api.example/api/v1/ws',
      'http://private@evil.example/42',
    ),
  ).toThrow()
})
it('does not send note text, tokens, URLs, props, locals or exception messages', () => {
  const event = {
    type: undefined,
    message: 'private-note',
    request: { url: 'https://api.example/ws?token=private-token' },
    user: { id: 'private-user' },
    extra: { props: 'private-props' },
    breadcrumbs: [{ message: 'private-note' }],
    exception: {
      values: [
        {
          type: 'Error',
          value: 'private-note',
          stacktrace: {
            frames: [
              {
                filename: 'app.js?token=private-token',
                function: 'save',
                lineno: 5,
                vars: { password: 'private-password' },
              },
            ],
          },
        },
      ],
    },
  }
  const result = scrubEvent(event)
  expect(JSON.stringify(result)).not.toContain('private-')
  expect(result.exception?.values?.[0]?.stacktrace?.frames?.[0]?.function).toBe('save')
})
