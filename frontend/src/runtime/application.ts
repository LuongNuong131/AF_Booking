import { effectScope, watch } from 'vue'
import { realtimeEvents } from './performance'
import type { Pinia } from 'pinia'
import type { Router } from 'vue-router'
import { configureApiSession } from '../api/session'
import { endpoints } from '../api/client'
import { useRealtime } from '../composables/useRealtime'
import { installRouteResilience } from '../composables/useRouteResilience'
import { useOutboxStore } from '../stores/outbox'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { useRealtimeStore } from '../stores/realtime'
import { useNotificationsStore } from '../stores/notifications'
import { useBookingsStore } from '../stores/bookings'
import { useTasksStore } from '../stores/tasks'
import { useFoldersStore } from '../stores/folders'
import { useCollaborationStore } from '../stores/collaboration'
import { useSystemHealthStore } from '../stores/systemHealth'
import { useRecentBookingsStore } from '../stores/recentBookings'
import { i18n } from '../i18n'
import { installTaskAlerts } from '../composables/useTaskAlerts'
import { notificationText } from '../utils/notificationText'
import { useRequest } from '../composables/useRequest'
import { api } from '../api/client'
import { parseUser } from '../api/auth-payload'
import { timeouts } from '../config/timeouts'

export function installApplication(pinia: Pinia, router: Router): () => void {
  const scope = effectScope()
  const auth = useAuthStore(pinia),
    ui = useUiStore(pinia),
    realtime = useRealtimeStore(pinia)
  const notifications = useNotificationsStore(pinia),
    tasks = useTasksStore(pinia),
    bookings = useBookingsStore(pinia)
  const folders = useFoldersStore(pinia)
  const outbox = useOutboxStore(pinia)
  const collaboration = useCollaborationStore(pinia),
    recent = useRecentBookingsStore(pinia)
  const collaborationStop = outbox.subscribe((entry, result) => {
    if (result && 'note' in result) {
      void collaboration.acceptNote(
        entry.key,
        result.my_watching,
        entry.note.created_at,
        entry.attempts > 1,
      )
      collaboration.changed()
    }
  })
  const bootstrap = useRequest(
    async (ctx) =>
      Promise.all([
        identityRequest.run(),
        bookings.catalogue(ctx),
        bookings.list(ctx, '/bookings/mine', { page: 1, size: 10 }),
        tasks.refreshDue(true),
        notifications.refresh(),
        collaboration.refreshCount(),
      ]),
    { timeoutMs: timeouts.list },
  )
  let frameId = 0
  const batch = new Map<string, import('../types/api.generated').BookingUpdatedData>()
  function flushFrames() {
    frameId = 0
    for (const data of batch.values()) {
      realtime.apply({ event: 'booking.updated', data })
      bookings.observe(data)
      tasks.bookingUpdated(data)
    }
    batch.clear()
  }
  const foldersStop = bookings.subscribe(folders.observe)
  const catalogueRequest = useRequest((ctx) => bookings.catalogue(ctx, true), {
    timeoutMs: timeouts.list,
    retry: true,
  })
  const identityRequest = useRequest(
    async ({ signal, timeoutMs }) =>
      parseUser((await api.get('/auth/me', { signal, timeout: timeoutMs })).data),
    { timeoutMs: timeouts.list, retry: true },
  )
  const themeStop = ui.startTheme()
  const routeStop = installRouteResilience(router, pinia)
  const alerts = installTaskAlerts(pinia, router)
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
        useSystemHealthStore(pinia).reset()
        notifications.reset()
        collaboration.reset()
        recent.reset(token ? auth.user!.id : null)
        ui.paletteOpen = false
        tasks.reset()
        outbox.stop()
        bootstrap.cancel()
        cancelAnimationFrame(frameId)
        frameId = 0
        batch.clear()
        bookings.reset()
        folders.reset(token ? (auth.user?.id ?? null) : null)
        catalogueRequest.cancel()
        identityRequest.cancel()
        if (!token) {
          ui.clearNotices('workspace')
          return
        }
        ui.clearNotices()
        outbox.start(auth.user!.id)
        void bootstrap.run()
        const preload = () => {
          void import('../views/SummaryView.vue')
        }
        if ('requestIdleCallback' in window) window.requestIdleCallback(preload)
        else setTimeout(preload, 1000)
        transport = useRealtime({
          url: endpoints.wsUrl,
          token,
          activeKey: () => realtime.activeBookingKey,
          onState: (state) => {
            realtime.state = state
            if (state !== 'connected') realtime.locks = {}
          },
          onFrame: (frame) => {
            if (import.meta.env.DEV) realtimeEvents.value++
            if (frame.event === 'system.health' && auth.user?.role === 'admin')
              useSystemHealthStore(pinia).degraded = frame.data.degraded
            if (frame.event === 'catalog.updated') {
              bookings.invalidateCatalogue()
              folders.invalidate()
              if (frame.data.resource === 'statuses') void catalogueRequest.run()
              else {
                const generation = auth.epoch
                void identityRequest.run().then((user) => {
                  if (user && generation === auth.epoch) auth.user = user
                })
              }
              ui.requestRefresh('catalogue')
            }
            if (frame.event === 'booking.updated') {
              const previous = batch.get(frame.data.booking_key)
              if (!previous || previous.version < frame.data.version)
                batch.set(frame.data.booking_key, frame.data)
              if (!frameId) frameId = requestAnimationFrame(flushFrames)
            } else realtime.apply(frame)
            if (frame.event === 'task.due') {
              notifications.incoming({
                id: frame.data.notification_id,
                booking_key: frame.data.task.booking_key,
                display_key: frame.data.task.display_key,
                by_agent_name: null,
                created_at: frame.data.created_at,
                type: 'task_due',
              })
              if (tasks.incoming(frame.data)) alerts.alert(frame.data.task)
            }
            if (frame.event === 'notification.new') {
              notifications.incoming(frame.data)
              if (frame.data.type === 'assigned' || frame.data.type === 'assignment_done')
                collaboration.changed()
              if (frame.data.type === 'task_due') tasks.invalidate()
              ui.notify(notificationText(frame.data))
            }
          },
          onReady: (reconnected) => {
            outbox.retry()
            if (reconnected) {
              ui.requestRefresh('reconnect')
              void tasks.refreshDue(true)
            }
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
        if (auth.isAuthenticated) {
          void notifications.refresh()
          void collaboration.refreshCount()
          if (ui.refreshReason === 'visible') void tasks.refreshDue(true)
        }
      },
    )
  })
  const online = () => {
    transport?.resume()
    outbox.retry()
  }
  window.addEventListener('online', online)
  return () => {
    collaborationStop()
    alerts.stop()
    outbox.stop()
    bootstrap.cancel()
    cancelAnimationFrame(frameId)
    scope.stop()
    transport?.stop()
    realtime.bindSender(null)
    notifications.reset()
    collaboration.reset()
    recent.reset()
    ui.paletteOpen = false
    tasks.reset()
    bookings.reset()
    folders.reset()
    foldersStop()
    catalogueRequest.cancel()
    identityRequest.cancel()
    ui.clearNotices()
    apiStop()
    routeStop()
    themeStop()
    window.removeEventListener('online', online)
  }
}
