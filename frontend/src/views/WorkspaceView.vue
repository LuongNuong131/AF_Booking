<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import BookingKeyText from '../components/BookingKeyText.vue'
const { t } = useI18n()
const route = useRoute()
</script>
<template>
  <section class="page-shell">
    <div class="page-heading">
      <p class="page-eyebrow">{{ t('app.workspace') }}</p>
      <h1>{{ t(route.meta.titleKey || 'app.name') }}</h1>
      <p>{{ t(route.meta.descriptionKey || 'pages.homeDescription') }}</p>
    </div>
    <BookingKeyText v-if="route.name === 'booking'" :booking-key="String(route.params.key)" />
  </section>
</template>
