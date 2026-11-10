<script setup lang="ts">
import { computed, ref, defineAsyncComponent, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useSystemHealthStore } from '../stores/systemHealth'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { useRealtimeStore } from '../stores/realtime'
import { useWorkspaceShortcuts } from '../composables/useBookingShortcuts'
import BaseIcon from '../components/BaseIcon.vue'
import BrandMark from '../components/BrandMark.vue'
import UserAvatar from '../components/UserAvatar.vue'
import NotificationBell from '../components/NotificationBell.vue'
import ThemeMenu from '../components/ThemeMenu.vue'
import LanguageSelect from '../components/LanguageSelect.vue'
import ShortcutHelp from '../components/ShortcutHelp.vue'
import TaskOverlays from '../components/TaskOverlays.vue'
import OutboxPanel from '../components/OutboxPanel.vue'
import ErrorBoundary from '../components/ErrorBoundary.vue'
const CommandPalette = defineAsyncComponent(() => import('../components/CommandPalette.vue'))
const DevPerformance = import.meta.env.DEV
  ? defineAsyncComponent(() => import('../components/DevPerformance.vue'))
  : null
const { t } = useI18n()
const auth = useAuthStore(),
  ui = useUiStore(),
  realtime = useRealtimeStore(),
  health = useSystemHealthStore()
const route = useRoute(),
  router = useRouter()
const mobileOpen = ref(false)
const menuTrigger = ref<HTMLButtonElement | null>(null)
const sidebar = ref<HTMLElement | null>(null)
watch(mobileOpen, async open => {
  await nextTick()
  if (open) sidebar.value?.querySelector<HTMLElement>('.nav-item')?.focus()
  else menuTrigger.value?.focus()
})
useWorkspaceShortcuts()
const links = computed(() => [
  { name: 'home', icon: 'home' },
  { name: 'summary', icon: 'grid' },
  { name: 'reports', icon: 'chart' },
  { name: 'tickets', icon: 'inbox' },
  { name: 'profile', icon: 'user' },
  ...(auth.user?.role === 'admin' ? [{ name: 'admin', icon: 'shield' }] : []),
])
const currentPage = computed(() => t(String(route.meta.titleKey || 'app.workspace')))
async function logout() {
  await auth.logout()
  await router.replace({ name: 'login' })
}
</script>
<template>
  <div class="workspace" :class="{ 'mobile-nav-open': mobileOpen }" @keydown.esc="mobileOpen = false">
    <a href="#main-content" class="skip-link">{{ t('nav.skip') }}</a>
    <aside ref="sidebar" class="sidebar">
      <RouterLink to="/" class="brand" @click="mobileOpen = false"
        ><BrandMark />
        <span
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
              route.name === link.name ||
              (link.name === 'summary' &&
                ['booking', 'summary-folder', 'note-search'].includes(String(route.name))) ||
              (link.name === 'reports' && ['daily-report', 'my-daily-report'].includes(String(route.name))) ||
              (link.name === 'admin' && String(route.name).startsWith('admin-')),
          }"
          @click="mobileOpen = false"
          ><BaseIcon :name="link.icon" /><span>{{ t(`nav.${link.name}`) }}</span
          ><span
            v-if="link.name === 'admin' && health.degraded"
            class="admin-degraded-dot"
            :aria-label="t('opsUi.degraded')"
        /></RouterLink>
      </nav>
      <div class="sidebar-bottom">
        <div class="workspace-note"><span class="workspace-note-line" />{{ t('app.footer') }}</div>
        <button type="button" class="sidebar-help" @click="ui.shortcutHelp = true">
          <BaseIcon name="keyboard" /><span>{{ t('shortcuts.open') }}</span
          ><kbd>{{ t('shortcuts.keys.help') }}</kbd>
        </button>
      </div>
    </aside>
    <button
      v-if="mobileOpen"
      type="button"
      class="mobile-nav-backdrop"
      :aria-label="t('nav.toggle')"
      @click="mobileOpen = false"
    />
    <div class="main-panel">
      <header class="topbar">
        <div class="topbar-context">
          <button
            type="button"
            ref="menuTrigger"
            class="icon-button mobile-toggle"
            :aria-label="t('nav.toggle')"
            :aria-expanded="mobileOpen"
            @click="mobileOpen = !mobileOpen"
          >
            <BaseIcon name="menu" /></button
          ><RouterLink class="mobile-brand-title" to="/"><BrandMark /><span>{{ t('app.name') }}</span></RouterLink><span class="workspace-label">{{ t('app.workspace') }}</span
          ><BaseIcon name="chevron" class="context-chevron" /><span class="topbar-page">{{ currentPage }}</span><span
            class="connection-status"
            :class="realtime.state"
            :aria-label="t('realtime.label', { state: t(`realtime.${realtime.state}`) })"
            ><span class="status-dot" />{{ t(`realtime.${realtime.state}`) }}</span
          >
        </div>
        <div class="header-actions">
          <button type="button" class="button palette-trigger" :aria-label="t('collabUi.palette')" :title="t('collabUi.palette')" @click="ui.paletteOpen = true">
            <BaseIcon name="search" /><span class="palette-label">{{ t('collabUi.palette') }}</span> <kbd>Ctrl+K</kbd></button
          ><OutboxPanel /><LanguageSelect /><ThemeMenu /><button
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
    <ShortcutHelp /><CommandPalette v-if="ui.paletteOpen" />
    <component :is="DevPerformance" v-if="DevPerformance" /><TaskOverlays />
  </div>
</template>
