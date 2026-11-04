<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { usePwaStore } from '../stores/pwa'
import { useUiStore } from '../stores/ui'
const { t } = useI18n(),
  store = usePwaStore()
function reload() {
  const worker = store.registration?.waiting
  if (!worker && !store.controllerChanged) return
  if (!window.dispatchEvent(new Event('booking:prepare-reload', { cancelable: true }))) {
    useUiStore().notify(t('bookingUi.draftFailed'), 'error')
    return
  }
  store.reloading = true
  if (worker) worker.postMessage({ type: 'SKIP_WAITING' })
  else window.location.reload()
}
</script>
<template>
  <aside v-if="store.updateReady" class="pwa-update-banner" role="status">
    <span>{{ t('new_version') }}</span
    ><button type="button" class="button primary" :disabled="store.reloading" @click="reload">
      {{ t('opsUi.reload') }}
    </button>
  </aside>
</template>
