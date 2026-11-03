<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { summaryReturn } from '../utils/summaryFilters'
import BookingWorkspace from '../components/BookingWorkspace.vue'
import { parseBookingKey, formatBookingKey } from '../utils/bookingKey'
const { t } = useI18n(),
  route = useRoute(),
  router = useRouter()
const key = computed(() => String(route.params.key))
const cw = computed(() => parseBookingKey(key.value)?.cw_number)
</script>
<template>
  <section class="booking-detail-view">
    <header class="page-heading detail-heading">
      <button
        type="button"
        class="text-button"
        @click="router.push(summaryReturn(route.query.from))"
      >
        {{
          t(
            summaryReturn(route.query.from).startsWith('/summary/folders/')
              ? 'folderUi.backToFolder'
              : 'bookingUi.backToSummary',
          )
        }}
      </button>
      <nav class="folder-breadcrumbs" :aria-label="t('folderUi.breadcrumb')">
        <RouterLink to="/summary">{{ t('pages.summaryTitle') }}</RouterLink
        ><template v-if="cw"
          ><span aria-hidden="true">›</span
          ><RouterLink
            :to="{
              name: 'summary-folder',
              params: { cw },
              query: { from: '/summary?view=folders' },
            }"
            >{{ cw }}</RouterLink
          ></template
        ><span aria-hidden="true">›</span
        ><span aria-current="page">{{ formatBookingKey(key) }}</span>
      </nav>
      <h1>{{ t('pages.bookingTitle') }}</h1>
    </header>
    <BookingWorkspace :initial-key="key" detail />
  </section>
</template>
