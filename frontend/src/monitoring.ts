import type { App } from 'vue'
import type { ErrorEvent } from '@sentry/vue'
import { sentryOrigin } from './config/sentry'
export function scrubEvent(event: ErrorEvent): ErrorEvent {
  return {
    type: undefined,
    event_id: event.event_id,
    timestamp: event.timestamp,
    platform: event.platform,
    level: event.level,
    release: event.release,
    environment: event.environment,
    exception: event.exception
      ? {
          values: event.exception.values?.slice(0, 5).map((error) => ({
            type: error.type,
            value: 'An application error occurred.',
            stacktrace: {
              frames: error.stacktrace?.frames?.slice(-50).map((frame) => ({
                filename: frame.filename?.split('?')[0],
                function: frame.function,
                module: frame.module,
                lineno: frame.lineno,
                in_app: frame.in_app,
              })),
            },
          })),
        }
      : undefined,
  }
}
export async function initializeMonitoring(
  app: App,
  dsn = import.meta.env.VITE_SENTRY_DSN,
): Promise<boolean> {
  if (!sentryOrigin(dsn)) return false
  const sentry = await import('@sentry/vue')
  sentry.init({
    dsn,
    app,
    attachProps: false,
    defaultIntegrations: false,
    integrations: [
      sentry.vueIntegration({ app, attachProps: false }),
      sentry.globalHandlersIntegration({ onerror: true, onunhandledrejection: true }),
    ],
    dataCollection: {
      userInfo: false,
      cookies: false,
      httpHeaders: false,
      httpBodies: [],
      urlQueryParams: false,
    },
    tracesSampleRate: undefined,
    beforeSend: scrubEvent,
    beforeBreadcrumb: () => null,
  })
  return true
}
