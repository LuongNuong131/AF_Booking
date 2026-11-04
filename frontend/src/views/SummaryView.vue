<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import SummaryBookings from './SummaryBookings.vue'
import SummaryFolders from './SummaryFolders.vue'
const route = useRoute(),
  router = useRouter(),
  { t } = useI18n()
const mode = computed(() => (route.query.view === 'folders' ? 'folders' : 'bookings'))
function change(value: 'bookings' | 'folders') {
  const query = { ...route.query }
  delete query.page
  if (value === 'folders') query.view = 'folders'
  else delete query.view
  void router.push({ name: 'summary', query })
}
</script>
<template>
  <div class="summary-mode-nav" role="group" :aria-label="t('folderUi.summaryMode')">
    <button
      v-for="value in ['bookings', 'folders'] as const"
      :key="value"
      type="button"
      class="button"
      :class="{ selected: mode === value }"
      :aria-pressed="mode === value"
      @click="change(value)"
    >
      {{ t(`folderUi.${value}`) }}
    </button>
    <RouterLink class="button" :to="{ name: 'note-search' }">{{
      t('opsUi.noteSearch')
    }}</RouterLink>
  </div>
  <SummaryFolders v-if="mode === 'folders'" /><SummaryBookings v-else />
</template>
