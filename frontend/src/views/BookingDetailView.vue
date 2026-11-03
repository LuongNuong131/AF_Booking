<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { summaryReturn } from '../utils/summaryFilters'
import BookingWorkspace from '../components/BookingWorkspace.vue'
const { t } = useI18n(),
  route = useRoute(),
  router = useRouter()
const key = computed(() => String(route.params.key))
</script>
<template>
  <section class="booking-detail-view">
    <header class="page-heading detail-heading">
      <button
        type="button"
        class="text-button"
        @click="router.push(summaryReturn(route.query.from))"
      >
        {{ t('bookingUi.backToSummary') }}
      </button>
      <h1>{{ t('pages.bookingTitle') }}</h1>
    </header>
    <BookingWorkspace :initial-key="key" detail />
  </section>
</template>
