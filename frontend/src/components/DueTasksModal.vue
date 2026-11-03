<script setup lang="ts">
import { ElDialog } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useTasksStore } from '../stores/tasks'
import { formatDateTime } from '../utils/dateTime'
import BaseIcon from './BaseIcon.vue'
const { t } = useI18n(),
  tasks = useTasksStore()
function viewTasks() {
  tasks.rightTab = 'tasks'
  tasks.summaryOpen = false
  tasks.openBookingRequest = { key: '', note: false, seq: Date.now() }
}
</script>
<template>
  <ElDialog
    v-model="tasks.summaryOpen"
    :title="t('tasks_due_modal', { n: tasks.dueCount })"
    :show-close="false"
    width="560px"
    align-center
    class="due-tasks-dialog"
    ><template #header
      ><div class="dialog-heading">
        <h2>{{ t('tasks_due_modal', { n: tasks.dueCount }) }}</h2>
        <button
          type="button"
          class="icon-button"
          :aria-label="t('common.close')"
          @click="tasks.summaryOpen = false"
        >
          <BaseIcon name="close" />
        </button></div
    ></template>
    <article v-for="task in tasks.dueTasks.slice(0, 10)" :key="task.id" class="due-summary-row">
      <div>
        <strong>{{ task.display_key }}</strong>
        <p>{{ task.message }}</p>
        <time>{{ formatDateTime(task.remind_at, tasks.preferences.timezone) }}</time>
      </div>
      <button type="button" class="button" @click="tasks.openBooking(task.booking_key)">
        {{ t('taskUi.openBooking') }}
      </button>
    </article>
    <p v-if="tasks.dueCount > 10" class="muted">
      {{ t('taskUi.moreDue', { count: tasks.dueCount - 10 }) }}
    </p>
    <template #footer
      ><button type="button" class="button primary" @click="viewTasks">
        {{ t('taskUi.viewTasks') }}
      </button></template
    ></ElDialog
  >
</template>
