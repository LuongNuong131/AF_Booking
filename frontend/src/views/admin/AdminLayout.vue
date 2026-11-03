<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
const sections = ['users', 'audit', 'bookings', 'trash', 'statuses', 'suppliers']
</script>
<template>
  <section class="admin-layout">
    <header class="page-heading">
      <p class="page-eyebrow">{{ t('app.workspace') }}</p>
      <h1>{{ t('pages.adminTitle') }}</h1>
      <p>{{ t('adminUi.description') }}</p>
    </header>
    <nav class="admin-tabs" :aria-label="t('pages.adminTitle')">
      <RouterLink v-for="section in sections" :key="section" :to="'/admin/' + section">{{
        t(`adminUi.${section}`)
      }}</RouterLink>
    </nav>
    <RouterView />
  </section>
</template>
