<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, provide, watch } from 'vue'
import { ElConfigProvider } from 'element-plus'
import enLocale from 'element-plus/es/locale/lang/en'
import viLocale from 'element-plus/es/locale/lang/vi'
import { validLanguage } from './i18n'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useUiStore } from './stores/ui'
import { createShortcutRegistry, shortcutRegistryKey } from './composables/useBookingShortcuts'
import BaseIcon from './components/BaseIcon.vue'
import BrandMark from './components/BrandMark.vue'
import ErrorBoundary from './components/ErrorBoundary.vue'
import PwaUpdateBanner from './components/PwaUpdateBanner.vue'
const { t, locale } = useI18n()
const componentLocale = computed(() => locale.value === 'vi' ? viLocale : enLocale)
watch(locale, value => { document.documentElement.lang = value }, { immediate: true })
function syncLanguage(event: StorageEvent) {
  if (event.key === 'booking.language') locale.value = validLanguage(event.newValue)
}
onMounted(() => window.addEventListener('storage', syncLanguage))
onBeforeUnmount(() => window.removeEventListener('storage', syncLanguage))
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
  <ElConfigProvider :locale="componentLocale">
  <PwaUpdateBanner />
  <div v-if="ui.routeFailed" class="route-retry global-route-retry" role="alert">
    <span>{{ t('route.slow') }}</span
    ><button type="button" class="text-button" @click="retryRoute">
      {{ t('route.retry') }}
    </button>
  </div>
  <ErrorBoundary :reset-key="route.fullPath"
    ><RouterView v-if="route.meta.public || auth.isAuthenticated" />
    <div v-else class="initial-shell">
      <BrandMark />
      <span>{{ t('common.loading') }}</span>
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
  </ElConfigProvider>
</template>
