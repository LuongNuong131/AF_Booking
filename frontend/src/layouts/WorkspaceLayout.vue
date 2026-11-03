<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { useRealtimeStore } from '../stores/realtime'
import { useWorkspaceShortcuts } from '../composables/useBookingShortcuts'
import BaseIcon from '../components/BaseIcon.vue'
import UserAvatar from '../components/UserAvatar.vue'
import NotificationBell from '../components/NotificationBell.vue'
import ThemeMenu from '../components/ThemeMenu.vue'
import ShortcutHelp from '../components/ShortcutHelp.vue'
import ErrorBoundary from '../components/ErrorBoundary.vue'
const { t } = useI18n()
const auth = useAuthStore(),
  ui = useUiStore(),
  realtime = useRealtimeStore()
const route = useRoute(),
  router = useRouter()
const mobileOpen = ref(false)
useWorkspaceShortcuts()
const links = computed(() => [
  { name: 'home', icon: 'home' },
  { name: 'summary', icon: 'grid' },
  ...(auth.user && ['admin', 'qc'].includes(auth.user.role)
    ? [{ name: 'reports', icon: 'chart' }]
    : []),
  { name: 'profile', icon: 'user' },
  ...(auth.user?.role === 'admin' ? [{ name: 'admin', icon: 'shield' }] : []),
])
async function logout() {
  await auth.logout()
  await router.replace({ name: 'login' })
}
</script>
<template>
  <div class="workspace" :class="{ 'mobile-nav-open': mobileOpen }">
    <a href="#main-content" class="skip-link">{{ t('nav.skip') }}</a>
    <aside class="sidebar">
      <RouterLink to="/" class="brand" @click="mobileOpen = false"
        ><span class="brand-mark" aria-hidden="true">{{ t('app.initial') }}</span
        ><span
          >{{ t('app.name') }}<small>{{ t('app.workspace') }}</small></span
        ></RouterLink
      >
      <nav :aria-label="t('app.navigationLabel')">
        <RouterLink
          v-for="link in links"
          :key="link.name"
          :to="{ name: link.name }"
          class="nav-item"
          :class="{
            active:
              route.name === link.name || (link.name === 'summary' && route.name === 'booking'),
          }"
          @click="mobileOpen = false"
          ><BaseIcon :name="link.icon" /><span>{{ t(`nav.${link.name}`) }}</span></RouterLink
        >
      </nav>
      <div class="sidebar-bottom">
        <div class="workspace-note"><span class="workspace-note-line" />{{ t('app.footer') }}</div>
        <button type="button" class="sidebar-help" @click="ui.shortcutHelp = true">
          <BaseIcon name="keyboard" /><span>{{ t('shortcuts.open') }}</span
          ><kbd>{{ t('shortcuts.keys.help') }}</kbd>
        </button>
      </div>
    </aside>
    <div class="main-panel">
      <header class="topbar">
        <div class="topbar-context">
          <button
            type="button"
            class="icon-button mobile-toggle"
            :aria-label="t('nav.toggle')"
            :aria-expanded="mobileOpen"
            @click="mobileOpen = !mobileOpen"
          >
            <BaseIcon name="menu" /></button
          ><span class="workspace-label">{{ t('app.workspace') }}</span
          ><span
            class="connection-status"
            :class="realtime.state"
            :aria-label="t('realtime.label', { state: t(`realtime.${realtime.state}`) })"
            ><span class="status-dot" />{{ t(`realtime.${realtime.state}`) }}</span
          >
        </div>
        <div class="header-actions">
          <ThemeMenu /><button
            type="button"
            class="icon-button desktop-help"
            :aria-label="t('shortcuts.open')"
            :title="t('shortcuts.open')"
            @click="ui.shortcutHelp = true"
          >
            <BaseIcon name="help" /></button
          ><NotificationBell /><span class="header-divider" /><RouterLink
            :to="{ name: 'profile' }"
            class="user-link"
            ><UserAvatar :name="auth.user?.full_name || ''" small /><span class="user-label"
              ><strong>{{ auth.user?.full_name }}</strong
              ><small>{{ t(`roles.${auth.user?.role || 'agent'}`) }}</small></span
            ></RouterLink
          ><button
            type="button"
            class="icon-button"
            :disabled="auth.signingOut"
            :aria-label="t('auth.signOut')"
            :title="t('auth.signOut')"
            @click="logout"
          >
            <BaseIcon name="logout" />
          </button>
        </div>
      </header>
      <main id="main-content" tabindex="-1">
        <div v-if="ui.routeLoading" class="route-progress" role="status">
          {{ t('common.loading') }}
        </div>
        <ErrorBoundary :reset-key="route.fullPath"><RouterView /></ErrorBoundary>
      </main>
    </div>
    <ShortcutHelp />
  </div>
</template>
