<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
const failed = ref(false)
onErrorCaptured(() => { failed.value = true; return false })
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <RouterLink to="/" class="brand">
        <span class="brand-mark" aria-hidden="true">{{ t('app.initial') }}</span>
        <span>{{ t('app.name') }}<small>{{ t('app.workspace') }}</small></span>
      </RouterLink>
      <nav :aria-label="t('app.navigationLabel')">
        <RouterLink to="/" class="nav-item"><span aria-hidden="true">◫</span>{{ t('app.overview') }}</RouterLink>
      </nav>
      <p class="sidebar-footer">{{ t('app.footer') }}</p>
    </aside>
    <div class="main-panel">
      <header class="topbar"><span>{{ t('app.workspace') }}</span><span class="version">{{ t('app.version') }}</span></header>
      <main id="main-content">
        <div v-if="failed" role="alert"><h1>{{ t('overview.errorTitle') }}</h1><p>{{ t('overview.errorBody') }}</p></div>
        <RouterView v-else />
      </main>
    </div>
  </div>
</template>
