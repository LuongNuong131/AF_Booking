<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useTasksStore } from '../stores/tasks'
import { addBusinessDays } from '../utils/taskDates'
import { zonedToday } from '../utils/summaryFilters'
import type { Task } from '../types/api.generated'
const props = defineProps<{ task: Task; compact?: boolean }>()
const { t } = useI18n(),
  tasks = useTasksStore()
async function snooze(days: number) {
  const p = tasks.preferences
  await tasks.mutate(props.task, 'snooze', {
    remind_date: addBusinessDays(zonedToday(p.timezone), days, p.skip_weekends),
    remind_time: p.default_remind_time,
  })
}
</script>
<template>
  <div class="task-actions" :class="{ compact }">
    <button type="button" class="text-button" @click="tasks.openBooking(task.booking_key)">
      {{ t('taskUi.openBooking') }}</button
    ><template v-if="task.status === 'pending'"
      ><button
        type="button"
        class="text-button"
        :disabled="tasks.busyIds.includes(task.id)"
        @click="tasks.mutate(task, 'complete')"
      >
        {{ t('taskUi.complete') }}
      </button>
      <details class="task-snooze">
        <summary class="text-button">{{ t('taskUi.snooze') }}</summary>
        <div class="snooze-options">
          <button type="button" :disabled="tasks.busyIds.includes(task.id)" @click="snooze(1)">
            {{ t('taskUi.tomorrow') }}</button
          ><button type="button" :disabled="tasks.busyIds.includes(task.id)" @click="snooze(3)">
            {{ t('taskUi.days', { days: 3 }) }}</button
          ><button type="button" @click="tasks.openDialog(task.booking_key, task, 'snooze')">
            {{ t('taskUi.chooseDate') }}
          </button>
        </div>
      </details>
      <button
        v-if="!compact"
        type="button"
        class="text-button"
        :disabled="tasks.busyIds.includes(task.id)"
        @click="tasks.mutate(task, 'cancel')"
      >
        {{ t('taskUi.cancel') }}
      </button></template
    >
  </div>
</template>
