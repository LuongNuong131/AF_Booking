<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElDialog } from 'element-plus'
import 'element-plus/es/components/dialog/style/css'
import { useI18n } from 'vue-i18n'
import { useTasksStore } from '../stores/tasks'
import { useRequest } from '../composables/useRequest'
import type { TaskCreate } from '../types/api.generated'
import { timeouts } from '../config/timeouts'
import {
  addBusinessDays,
  quickReminderDate,
  confirmation,
  reminderParts,
  validateReminder,
} from '../utils/taskDates'
import { zonedToday } from '../utils/summaryFilters'
import { formatDateTime } from '../utils/dateTime'
import BookingKeyText from './BookingKeyText.vue'
import RequestStatus from './RequestStatus.vue'
import BaseIcon from './BaseIcon.vue'
const { t } = useI18n(),
  tasks = useTasksStore()
const config = { ...tasks.dialog! },
  prefs = tasks.preferences,
  existing = config.taskId ? tasks.records[config.taskId] : null
const initial = existing ? reminderParts(existing.remind_at, prefs.timezone) : null
const date = ref(
    initial?.date ??
      quickReminderDate(zonedToday(prefs.timezone), config.presetDays ?? 1, prefs.skip_weekends),
  ),
  time = ref(initial?.time ?? prefs.default_remind_time),
  message = ref(existing?.message ?? t('taskUi.defaultMessage')),
  skip = ref(prefs.skip_weekends),
  editingId = ref(config.taskId)
const messageRef = ref<HTMLInputElement | null>(null)
const mode = ref(config.mode),
  submitting = ref(false)
const today = computed(() => zonedToday(tasks.preferences.timezone)),
  maxDate = computed(() => addBusinessDays(today.value, 90, false))
const minDate = computed(() => {
  const old = editingId.value ? tasks.records[editingId.value] : null
  const original = old ? reminderParts(old.remind_at, tasks.preferences.timezone).date : today.value
  return mode.value === 'edit' && original < today.value ? original : today.value
})
const validation = computed(() => {
  const old = editingId.value ? tasks.records[editingId.value] : null
  if (old && mode.value === 'edit') {
    const p = reminderParts(old.remind_at, tasks.preferences.timezone)
    if (p.date === date.value && p.time === time.value) return null
  }
  return validateReminder(date.value, time.value, tasks.preferences.timezone)
})
const when = computed(() => confirmation(date.value, time.value, tasks.preferences.timezone))
const pending = computed(() =>
  (tasks.bookIds[config.key] ?? [])
    .map((id) => tasks.records[id])
    .filter((task) => task?.status === 'pending'),
)
const createRequest = useRequest(
  (ctx, payload: Omit<TaskCreate, 'client_request_id'>) => tasks.create(ctx, config.key, payload),
  { timeoutMs: timeouts.task },
)
const bookRequest = useRequest((ctx) => tasks.bookTasks(ctx, config.key), {
  timeoutMs: timeouts.list,
  retry: true,
})
const busy = computed(
  () =>
    submitting.value ||
    createRequest.pending.value ||
    (!!editingId.value && tasks.busyIds.includes(editingId.value)),
)
function close() {
  if (tasks.dialog?.nonce === config.nonce) tasks.dialog = null
}
function quick(days: number) {
  date.value = quickReminderDate(today.value, days, skip.value)
}
async function submit() {
  if (validation.value || busy.value) return
  const original = {
    date: date.value,
    time: time.value,
    message: message.value,
    id: editingId.value,
  }
  submitting.value = true
  try {
    let success = false
    if (editingId.value) {
      const task = tasks.records[editingId.value]
      if (task)
        success = await tasks.mutate(task, mode.value === 'snooze' ? 'snooze' : 'edit', {
          remind_date: date.value,
          remind_time: time.value,
          message: message.value.trim(),
        })
    } else
      success = !!(await createRequest.run({
        remind_date: date.value,
        remind_time: time.value,
        message: message.value.trim() || t('taskUi.defaultMessage'),
      }))
    if (success && tasks.dialog?.nonce === config.nonce) {
      await bookRequest.run()
      if (
        date.value === original.date &&
        time.value === original.time &&
        message.value === original.message &&
        editingId.value === original.id
      )
        close()
    }
  } finally {
    submitting.value = false
  }
}

function edit(id: number) {
  const task = tasks.records[id]
  if (!task) return
  const p = reminderParts(task.remind_at, tasks.preferences.timezone)
  editingId.value = id
  mode.value = 'edit'
  date.value = p.date
  time.value = p.time
  message.value = task.message
}
async function cancel(id: number) {
  const task = tasks.records[id]
  if (task && (await tasks.mutate(task, 'cancel'))) await bookRequest.run()
}
onMounted(() => {
  void bookRequest.run()
})
</script>
<template>
  <ElDialog
    :model-value="true"
    :title="t('taskUi.dialogTitle')"
    :show-close="false"
    width="640px"
    align-center
    class="task-dialog"
    @opened="messageRef?.focus()"
    @update:model-value="close"
    ><template #header
      ><div class="dialog-heading">
        <h2>{{ t('taskUi.dialogTitle') }}</h2>
        <button type="button" class="icon-button" :aria-label="t('common.close')" @click="close">
          <BaseIcon name="close" />
        </button></div></template
    ><BookingKeyText :booking-key="config.key" />
    <form class="task-form" :aria-label="t('taskUi.reminderForm')" @submit.prevent="submit">
      <div class="task-quick-days">
        <button
          v-for="days in [1, 2, 3, 5, 7]"
          :key="days"
          type="button"
          class="button"
          @click="quick(days)"
        >
          {{
            t(days === 1 ? 'taskUi.tomorrow' : days === 7 ? 'taskUi.week' : 'taskUi.days', { days })
          }}
        </button>
      </div>
      <label class="task-weekends"
        ><input v-model="skip" type="checkbox" />{{ t('taskUi.skipWeekends') }}</label
      >
      <div class="task-date-fields">
        <label
          >{{ t('taskUi.date')
          }}<input v-model="date" type="date" :min="minDate" :max="maxDate" required /></label
        ><label>{{ t('taskUi.time') }}<input v-model="time" type="time" required /></label>
      </div>
      <label class="task-message-field"
        >{{ t('taskUi.message')
        }}<input
          ref="messageRef"
          v-model="message"
          maxlength="255"
          :placeholder="t('taskUi.defaultMessage')"
      /></label>
      <p v-if="when" class="task-confirmation" role="status">
        {{ t('task_when', when) }}
      </p>
      <p v-if="validation" class="field-error" role="alert">
        {{ t(validation) }}
      </p>
      <button type="submit" class="button primary" :disabled="busy || !!validation">
        {{ t(busy ? 'taskUi.saving' : editingId ? 'taskUi.saveChanges' : 'taskUi.create') }}</button
      ><RequestStatus
        :state="createRequest.state.value"
        :error="createRequest.error.value"
        @retry="submit"
      /><RequestStatus
        :state="tasks.actionError ? 'error' : 'idle'"
        :error="tasks.actionError"
        @retry="submit"
      />
    </form>
    <section class="booking-pending-tasks">
      <h3>{{ t('taskUi.pendingForBooking', { count: pending.length }) }}</h3>
      <RequestStatus
        :state="bookRequest.state.value"
        :error="bookRequest.error.value"
        @retry="bookRequest.run"
      />
      <p v-if="!pending.length && !bookRequest.pending.value" class="muted">
        {{ t('taskUi.noPending') }}
      </p>
      <article v-for="task in pending" :key="task.id">
        <p>{{ task.message }}</p>
        <time :datetime="task.remind_at">{{
          formatDateTime(task.remind_at, tasks.preferences.timezone)
        }}</time>
        <div>
          <button type="button" class="text-button" @click="edit(task.id)">
            {{ t('taskUi.edit') }}</button
          ><button
            type="button"
            class="text-button"
            :disabled="tasks.busyIds.includes(task.id)"
            @click="cancel(task.id)"
          >
            {{ t('taskUi.cancel') }}
          </button>
        </div>
      </article>
      <p v-if="pending.length >= 5" class="booking-warning">
        {{ t('taskUi.limit') }}
      </p>
    </section></ElDialog
  >
</template>
