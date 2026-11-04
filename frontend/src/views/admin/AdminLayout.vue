<script setup lang="ts">
import { useSystemHealthStore } from '../../stores/systemHealth'
import { useI18n } from 'vue-i18n'
const { t } = useI18n(),
  health = useSystemHealthStore()
const sections = [
  'users',
  'audit',
  'bookings',
  'trash',
  'statuses',
  'suppliers',
  'integrity',
  'system',
]
</script>
<template>
  <section class="admin-layout">
    <header class="page-heading">
      <p class="page-eyebrow">{{ t('app.workspace') }}</p>
      <h1>{{ t('pages.adminTitle') }}</h1>
      <p>{{ t('adminUi.description') }}</p>
    </header>
    <nav class="admin-tabs" :aria-label="t('pages.adminTitle')">
      <RouterLink v-for="section in sections" :key="section" :to="'/admin/' + section"
        >{{ t(`adminUi.${section}`)
        }}<span
          v-if="section === 'system' && health.degraded"
          class="admin-degraded-dot"
          :aria-label="t('opsUi.degraded')"
      /></RouterLink>
    </nav>
    <RouterView />
  </section>
</template>
