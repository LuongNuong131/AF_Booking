<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
const props = defineProps<{
  page: number
  total: number
  size: number
  summaryKey?: 'bookingUi.pageOf' | 'taskUi.pageOf' | 'folderUi.pageOf'
}>()
const { t } = useI18n()
defineEmits<{ change: [page: number] }>()
const pages = computed(() => Math.max(1, Math.ceil(props.total / props.size)))
</script>
<template>
  <nav class="page-controls" :aria-label="t('bookingUi.pagination')">
    <span>{{ t(summaryKey ?? 'bookingUi.pageOf', { page, pages, total }) }}</span>
    <div>
      <button
        type="button"
        class="button"
        :disabled="page <= 1"
        :aria-label="t('bookingUi.previousPage')"
        @click="$emit('change', page - 1)"
      >
        {{ t('bookingUi.previous') }}</button
      ><button
        type="button"
        class="button"
        :disabled="page >= pages"
        :aria-label="t('bookingUi.nextPage')"
        @click="$emit('change', page + 1)"
      >
        {{ t('bookingUi.next') }}
      </button>
    </div>
  </nav>
</template>
