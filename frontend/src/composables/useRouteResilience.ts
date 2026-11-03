import type { Pinia } from 'pinia'
import { isNavigationFailure, NavigationFailureType, type Router } from 'vue-router'
import { useUiStore } from '../stores/ui'
import { i18n } from '../i18n'
import { timeouts } from '../config/timeouts'

export function installRouteResilience(router: Router, pinia: Pinia): () => void {
  const ui = useUiStore(pinia)
  let timer: ReturnType<typeof setTimeout> | undefined
  let hiddenAt: number | null = document.hidden ? Date.now() : null
  const before = router.beforeEach((to) => {
    clearTimeout(timer)
    ui.pendingPath = to.fullPath
    ui.routeFailed = false
    ui.routeLoading = true
    timer = setTimeout(() => {
      ui.routeLoading = false
      ui.routeFailed = true
    }, timeouts.routeWatchdog)
  })
  const after = router.afterEach((to, _from, failure) => {
    if (
      to.fullPath !== ui.pendingPath ||
      isNavigationFailure(failure, NavigationFailureType.cancelled)
    )
      return
    clearTimeout(timer)
    ui.routeLoading = false
    if (!failure) ui.routeFailed = false
    if (!ui.routeFailed) ui.pendingPath = to.fullPath
    document.title = `${i18n.global.t(to.meta.titleKey ?? 'app.name')} · ${i18n.global.t('app.name')}`
  })
  const failed = router.onError((_error, to) => {
    if (to.fullPath === ui.pendingPath) {
      clearTimeout(timer)
      ui.routeLoading = false
      ui.routeFailed = true
    }
  })
  const visibility = () => {
    if (document.hidden) hiddenAt = Date.now()
    else if (hiddenAt !== null) {
      if (Date.now() - hiddenAt >= timeouts.visibilityRefresh) ui.requestRefresh('visible')
      hiddenAt = null
    }
  }
  document.addEventListener('visibilitychange', visibility)
  return () => {
    clearTimeout(timer)
    before()
    after()
    failed()
    document.removeEventListener('visibilitychange', visibility)
  }
}
