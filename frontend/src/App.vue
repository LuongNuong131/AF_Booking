<script setup lang="ts">
import { provide } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useUiStore } from './stores/ui'
import { createShortcutRegistry, shortcutRegistryKey } from './composables/useBookingShortcuts'
import BaseIcon from './components/BaseIcon.vue'
import ErrorBoundary from './components/ErrorBoundary.vue'
const { t } = useI18n()
const auth = useAuthStore(),
  ui = useUiStore(),
  route = useRoute(),
  router = useRouter()
provide(shortcutRegistryKey, createShortcutRegistry())
async function retryRoute() {
  ui.routeFailed = false
  if (route.fullPath !== ui.pendingPath)
    await router.push(ui.pendingPath).catch(() => {
      ui.routeFailed = true
    })
  else ui.requestRefresh('retry')
}
</script>
<template>
  <div v-if="ui.routeFailed" class="route-retry global-route-retry" role="alert">
    <span>{{ t('route.slow') }}</span
    ><button type="button" class="text-button" @click="retryRoute">
      {{ t('route.retry') }}
    </button>
  </div>
  <ErrorBoundary :reset-key="route.fullPath"
    ><RouterView v-if="route.meta.public || auth.isAuthenticated" />
    <div v-else class="initial-shell">
      <span class="brand-mark" aria-hidden="true">{{ t('app.initial') }}</span
      ><span>{{ t('common.loading') }}</span>
    </div></ErrorBoundary
  >
  <div class="notice-stack" aria-live="polite" aria-relevant="additions">
    <div
      v-for="notice in ui.notices"
      :key="notice.id"
      class="notice"
      :class="notice.kind"
      :role="notice.kind === 'error' ? 'alert' : 'status'"
    >
      <span>{{ notice.message }}</span
      ><button
        type="button"
        class="icon-button small"
        :aria-label="t('common.dismiss')"
        @click="ui.dismiss(notice.id)"
      >
        <BaseIcon name="close" />
      </button>
    </div>
  </div>
</template>
