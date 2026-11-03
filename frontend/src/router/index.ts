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
            component: () => import('../views/HomeView.vue'),
            meta: {
              titleKey: 'pages.homeTitle',
              descriptionKey: 'pages.homeDescription',
            },
          },
          {
            path: 'summary',
            name: 'summary',
            component: () => import('../views/SummaryView.vue'),
            meta: {
              titleKey: 'pages.summaryTitle',
              descriptionKey: 'pages.summaryDescription',
            },
          },
          {
            path: 'summary/folders/:cw',
            name: 'summary-folder',
            component: () => import('../views/SummaryFolderView.vue'),
            meta: { titleKey: 'folderUi.folder' },
          },
          {
            path: 'summary/:key',
            name: 'booking',
            component: () => import('../views/BookingDetailView.vue'),
            meta: {
              titleKey: 'pages.bookingTitle',
              descriptionKey: 'pages.bookingDescription',
            },
          },
          {
            path: 'profile',
            name: 'profile',
            component: () => import('../views/ProfileView.vue'),
            meta: {
              titleKey: 'pages.profileTitle',
              descriptionKey: 'pages.profileDescription',
            },
          },
          {
            path: 'reports',
            name: 'reports',
            component: () => import('../views/ReportsView.vue'),
            meta: {
              titleKey: 'pages.reportsTitle',
              descriptionKey: 'pages.reportsDescription',
              roles: ['admin', 'qc'],
            },
          },
          {
            path: 'admin',
            component: () => import('../views/admin/AdminLayout.vue'),
            meta: {
              titleKey: 'pages.adminTitle',
              descriptionKey: 'pages.adminDescription',
              roles: ['admin'],
            },
            children: [
              { path: '', name: 'admin', redirect: { name: 'admin-users' } },
              {
                path: 'users',
                name: 'admin-users',
                component: () => import('../views/admin/AdminUsers.vue'),
              },
              {
                path: 'audit',
                name: 'admin-audit',
                component: () => import('../views/admin/AdminAudit.vue'),
              },
              {
                path: 'bookings',
                name: 'admin-bookings',
                component: () => import('../views/admin/AdminBookings.vue'),
              },
              {
                path: 'trash',
                name: 'admin-trash',
                component: () => import('../views/admin/AdminTrash.vue'),
              },
              {
                path: 'statuses',
                name: 'admin-statuses',
                component: () => import('../views/admin/AdminStatuses.vue'),
              },
              {
                path: 'suppliers',
                name: 'admin-suppliers',
                component: () => import('../views/admin/AdminSuppliers.vue'),
              },
            ],
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
    if (to.name === 'summary-folder') {
      const raw = String(to.params.cw ?? ''),
        cw = raw
          .trim()
          .toUpperCase()
          .replace(/^CW\s+/, 'CW')
      if (!/^CW\d{5,10}$/.test(cw)) return { name: 'summary', query: { view: 'folders' } }
      if (raw !== cw)
        return {
          name: 'summary-folder',
          params: { cw },
          query: to.query,
          replace: true,
        }
    }
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
