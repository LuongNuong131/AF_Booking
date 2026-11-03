import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'
import type { Pinia } from 'pinia'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { parseBookingKey } from '../utils/bookingKey'
import { i18n } from '../i18n'
import LoginView from '../views/LoginView.vue'
import type { PublicUser } from '../types/api.generated'

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    titleKey?: string
    descriptionKey?: string
    roles?: PublicUser['role'][]
  }
}
export function createAppRouter(pinia: Pinia, history: RouterHistory = createWebHistory()) {
  const router = createRouter({
    history,
    routes: [
      {
        path: '/login',
        name: 'login',
        component: LoginView,
        meta: { public: true, titleKey: 'auth.signIn' },
      },
      {
        path: '/',
        component: () => import('../layouts/WorkspaceLayout.vue'),
        children: [
          {
            path: '',
            name: 'home',
            component: () => import('../views/WorkspaceView.vue'),
            meta: { titleKey: 'pages.homeTitle', descriptionKey: 'pages.homeDescription' },
          },
          {
            path: 'summary',
            name: 'summary',
            component: () => import('../views/WorkspaceView.vue'),
            meta: { titleKey: 'pages.summaryTitle', descriptionKey: 'pages.summaryDescription' },
          },
          {
            path: 'summary/:key',
            name: 'booking',
            component: () => import('../views/WorkspaceView.vue'),
            meta: { titleKey: 'pages.bookingTitle', descriptionKey: 'pages.bookingDescription' },
          },
          {
            path: 'profile',
            name: 'profile',
            component: () => import('../views/ProfileView.vue'),
            meta: { titleKey: 'pages.profileTitle', descriptionKey: 'pages.profileDescription' },
          },
          {
            path: 'reports',
            name: 'reports',
            component: () => import('../views/WorkspaceView.vue'),
            meta: {
              titleKey: 'pages.reportsTitle',
              descriptionKey: 'pages.reportsDescription',
              roles: ['admin', 'qc'],
            },
          },
          {
            path: 'admin/:pathMatch(.*)*',
            name: 'admin',
            component: () => import('../views/WorkspaceView.vue'),
            meta: {
              titleKey: 'pages.adminTitle',
              descriptionKey: 'pages.adminDescription',
              roles: ['admin'],
            },
          },
        ],
      },
      { path: '/:pathMatch(.*)*', redirect: '/' },
    ],
  })
  router.beforeEach(async (to) => {
    const auth = useAuthStore(pinia)
    await auth.ensureSession()
    if (!to.meta.public && !auth.isAuthenticated)
      return { name: 'login', query: { redirect: to.fullPath } }
    if (to.name === 'login' && auth.isAuthenticated) return { name: 'home' }
    if (to.meta.roles && (!auth.user || !to.meta.roles.includes(auth.user.role)))
      return { name: 'home' }
    if (to.name === 'booking') {
      const raw = String(to.params.key ?? '')
      const parsed = parseBookingKey(raw)
      if (!parsed || !('key' in parsed)) {
        useUiStore(pinia).notify(i18n.global.t('invalid_key'), 'error')
        return { name: 'summary' }
      }
      if (raw !== parsed.key)
        return {
          name: 'booking',
          params: { key: parsed.key },
          query: to.query,
          hash: to.hash,
          replace: true,
        }
    }
    return true
  })
  return router
}

export { safeRedirect } from '../utils/navigation'
