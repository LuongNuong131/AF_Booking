<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTasksStore } from '../stores/tasks'
import { formatBookingKey } from '../utils/bookingKey'
import BaseIcon from './BaseIcon.vue'
const props = defineProps<{
  bookingKey: string
  count?: number
  compact?: boolean
  disabled?: boolean
}>()
const { t } = useI18n(),
  tasks = useTasksStore()
watch(
  () => [props.bookingKey, props.count] as const,
  ([key, count]) => tasks.seedCount(key, count),
  { immediate: true },
)
const count = computed(() => tasks.pendingCounts[props.bookingKey] ?? props.count ?? 0)
</script>
<template>
  <button
    type="button"
    :class="compact ? 'icon-button task-icon' : 'button task-button'"
    :disabled="disabled"
    :aria-label="t('taskUi.openFor', { key: formatBookingKey(bookingKey), count })"
    :title="t('taskUi.open')"
    @click.stop="tasks.openDialog(bookingKey)"
  >
    <BaseIcon name="bell" /><span v-if="!compact">{{ t('taskUi.task') }}</span
    ><span v-if="count" class="task-count">{{ count }}</span>
  </button>
</template>
