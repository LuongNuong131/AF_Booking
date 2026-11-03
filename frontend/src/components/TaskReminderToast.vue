<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useTasksStore } from '../stores/tasks'
import TaskActions from './TaskActions.vue'
import BaseIcon from './BaseIcon.vue'
const { t } = useI18n(),
  tasks = useTasksStore()
</script>
<template>
  <section
    v-if="tasks.reminderTasks.length"
    class="task-reminder-stack"
    :aria-label="t('taskUi.dueReminders')"
  >
    <article
      v-for="task in tasks.reminderTasks.slice(0, 3)"
      :key="`${task.id}:${task.remind_at}`"
      class="task-reminder-toast"
      role="alert"
    >
      <header>
        <strong>{{ t('task_due_toast', { key: task.display_key }) }}</strong
        ><button
          type="button"
          class="icon-button small"
          :aria-label="t('common.dismiss')"
          @click="tasks.dismissReminder(task.id)"
        >
          <BaseIcon name="close" />
        </button>
      </header>
      <p>{{ task.message }}</p>
      <TaskActions :task="task" compact />
    </article>
    <button
      v-if="tasks.reminderTasks.length > 3"
      type="button"
      class="button"
      @click="tasks.summaryOpen = true"
    >
      {{ t('tasks_due_modal', { n: tasks.dueCount }) }}
    </button>
  </section>
</template>
