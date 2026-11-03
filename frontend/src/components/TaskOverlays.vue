<script setup lang="ts">
import { watch, onScopeDispose } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useTasksStore } from '../stores/tasks'
import { useUiStore } from '../stores/ui'
import TaskDialog from './TaskDialog.vue'
import TaskReminderToast from './TaskReminderToast.vue'
import DueTasksModal from './DueTasksModal.vue'
import RequestStatus from './RequestStatus.vue'
const { t } = useI18n(),
  tasks = useTasksStore(),
  ui = useUiStore(),
  router = useRouter()
watch(
  () => !!tasks.dialog || tasks.summaryOpen,
  (value) => {
    ui.taskModalOpen = value
  },
  { immediate: true },
)
onScopeDispose(() => {
  ui.taskModalOpen = false
})
watch(
  () => tasks.openBookingRequest,
  (request) => {
    if (request && router.currentRoute.value.name !== 'home') void router.push({ name: 'home' })
  },
)
function openNote() {
  if (tasks.noteSuggestion) {
    tasks.openBooking(tasks.noteSuggestion, true)
    tasks.noteSuggestion = null
  }
}
</script>
<template>
  <TaskDialog v-if="tasks.dialog" :key="tasks.dialog.nonce" /><DueTasksModal /><TaskReminderToast />
  <aside v-if="tasks.noteSuggestion" class="task-note-suggestion" role="status">
    <span>{{ t('taskUi.notePrompt') }}</span
    ><button type="button" class="text-button" @click="openNote">{{ t('taskUi.addNote') }}</button
    ><button type="button" class="text-button" @click="tasks.noteSuggestion = null">
      {{ t('common.close') }}
    </button>
  </aside>
  <div
    v-if="tasks.dueRequest.state === 'error' || tasks.dueRequest.state === 'timeout'"
    class="task-sync-error"
  >
    <RequestStatus
      :state="tasks.dueRequest.state"
      :error="tasks.dueRequest.error"
      @retry="tasks.refreshDue(true)"
    />
  </div>
</template>
