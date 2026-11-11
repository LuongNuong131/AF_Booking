import { isFolderKey } from '../utils/folderKey'
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
        path: '/change-password',
        name: 'change-password',
        component: () => import('../views/RequiredPasswordView.vue'),
        meta: { titleKey: 'securityUi.changePassword' },
      },
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
            path: 'reports/daily',
            name: 'daily-report',
            component: () => import('../views/DailyReportView.vue'),
            meta: { titleKey: 'opsUi.dailyTitle', roles: ['admin', 'qc'] },
          },
          {
            path: 'search/notes',
            name: 'note-search',
            component: () => import('../views/NoteSearchView.vue'),
            meta: { titleKey: 'opsUi.noteSearch' },
          },
          {
            path: 'reports/mine',
            name: 'my-daily-report',
            component: () => import('../views/MyDailyReportView.vue'),
            meta: { titleKey: 'personalReportUi.title' },
          },
          {
            path: 'tickets',
            name: 'tickets',
            component: () => import('../views/TicketsView.vue'),
            meta: { titleKey: 'workTaskUi.nav' },
          },
          {
            path: 'reports',
            name: 'reports',
            component: () => import('../views/ReportsLanding.vue'),
            meta: {
              titleKey: 'pages.reportsTitle',
              descriptionKey: 'pages.reportsDescription',
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
              { path: 'data', name: 'admin-data', component: () => import('../views/admin/AdminData.vue') },
              { path: 'tickets', name: 'admin-tickets', component: () => import('../views/TicketsView.vue'), props: { management: true } },
              { path: 'import', name: 'admin-import', component: () => import('../views/admin/AdminImport.vue') },
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
              {
                path: 'system',
                name: 'admin-system',
                component: () => import('../views/admin/AdminSystem.vue'),
              },
              {
                path: 'integrity',
                name: 'admin-integrity',
                component: () => import('../views/admin/AdminIntegrity.vue'),
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
    if (
      auth.isAuthenticated &&
      auth.user?.must_change_password &&
      to.name !== 'change-password'
    )
      return { name: 'change-password' }
    if (to.name === 'change-password' && !auth.user?.must_change_password)
      return { name: 'home' }
    if (to.name === 'login' && auth.isAuthenticated) return { name: 'home' }
    if (to.meta.roles && (!auth.user || !to.meta.roles.includes(auth.user.role)))
      return { name: 'home' }
    if (to.name === 'summary-folder') {
      const raw = String(to.params.cw ?? ''),
        cw = raw
          .trim()
          .toUpperCase()
          .replace(/^CW\s+/, 'CW')
      if (!isFolderKey(cw)) return { name: 'summary', query: { view: 'folders' } }
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
