import { effectScope, watch } from 'vue'
import type { Pinia } from 'pinia'
import type { Router } from 'vue-router'
import { configureApiSession } from '../api/session'
import { endpoints } from '../api/client'
import { useRealtime } from '../composables/useRealtime'
import { installRouteResilience } from '../composables/useRouteResilience'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { useRealtimeStore } from '../stores/realtime'
import { useNotificationsStore } from '../stores/notifications'
import { useBookingsStore } from '../stores/bookings'
import { useTasksStore } from '../stores/tasks'
import { i18n } from '../i18n'
import { notificationText } from '../utils/notificationText'

export function installApplication(pinia: Pinia, router: Router): () => void {
  const scope = effectScope()
  const auth = useAuthStore(pinia),
    ui = useUiStore(pinia),
    realtime = useRealtimeStore(pinia)
  const notifications = useNotificationsStore(pinia),
    tasks = useTasksStore(pinia),
    bookings = useBookingsStore(pinia)
  const themeStop = ui.startTheme()
  const routeStop = installRouteResilience(router, pinia)
  let transport: ReturnType<typeof useRealtime> | null = null

  function endSession(replaced: boolean): void {
    const voluntary = auth.signingOut && !replaced
    ui.clearNotices()
    auth.expire()
    if (!voluntary)
      ui.notify(
        i18n.global.t(replaced ? 'session_replaced' : 'auth.sessionEnded'),
        'error',
        'session',
      )
    if (router.currentRoute.value.name !== 'login')
      void router.replace({ name: 'login' }).catch(() => {})
  }
  const apiStop = configureApiSession({
    identity: () => ({ token: auth.token, epoch: auth.epoch }),
    unauthorized: (code) => endSession(code === 'SESSION_REPLACED'),
    forbidden: () => ui.notify(i18n.global.t('errors.FORBIDDEN'), 'error'),
  })
  scope.run(() => {
    watch(
      () => (auth.isAuthenticated ? auth.token : null),
      (token) => {
        transport?.stop()
        transport = null
        realtime.bindSender(null)
        realtime.reset()
        notifications.reset()
        tasks.reset()
        bookings.reset()
        if (!token) {
          ui.clearNotices('workspace')
          return
        }
        ui.clearNotices()
        void notifications.refresh()
        transport = useRealtime({
          url: endpoints.wsUrl,
          token,
          activeKey: () => realtime.activeBookingKey,
          onState: (state) => {
            realtime.state = state
            if (state !== 'connected') realtime.locks = {}
          },
          onFrame: (frame) => {
            realtime.apply(frame)
            if (frame.event === 'booking.updated') bookings.observe(frame.data)
            if (frame.event === 'notification.new') {
              notifications.incoming(frame.data)
              if (frame.data.type === 'task_due') tasks.invalidate()
              ui.notify(notificationText(frame.data))
            }
          },
          onReady: (reconnected) => {
            if (reconnected) ui.requestRefresh('reconnect')
          },
          onForceLogout: (reason) => {
            if (reason === 'logout' && auth.signingOut) return
            endSession(reason === 'new_login' || reason === 'session_replaced')
          },
        })
        realtime.bindSender(transport.send)
        transport.start()
      },
      { immediate: true },
    )
    watch(
      () => ui.refreshVersion,
      () => {
        if (auth.isAuthenticated) void notifications.refresh()
      },
    )
  })
  const online = () => transport?.resume()
  window.addEventListener('online', online)
  return () => {
    scope.stop()
    transport?.stop()
    realtime.bindSender(null)
    notifications.reset()
    tasks.reset()
    bookings.reset()
    ui.clearNotices()
    apiStop()
    routeStop()
    themeStop()
    window.removeEventListener('online', online)
  }
}
