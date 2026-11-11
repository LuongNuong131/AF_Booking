<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import { ticketTitles, englishTicket, type IssueType } from '../utils/ticket'
import type { Attachment, WorkTaskItem } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
import StagedImages from './StagedImages.vue'
import TicketTranslation from './TicketTranslation.vue'
const props = defineProps<{ bookingKey: string }>()
const emit = defineEmits<{ created: [ticket: WorkTaskItem] }>()
const root = ref<HTMLDetailsElement | null>(null)
const { t } = useI18n(), message = ref(''), issue = ref<IssueType>('contract'), requestId = ref(crypto.randomUUID()), images = ref<File[]>([])
const savedTicket = ref<WorkTaskItem | null>(null)
const title = computed(() => `${ticketTitles[issue.value]} - ${props.bookingKey}`)
const valid = computed(() => englishTicket(message.value.trim()))
const create = useRequest(async ({ signal, timeoutMs }) => {
  if (!savedTicket.value) savedTicket.value = (await api.post<WorkTaskItem>(`/bookings/${props.bookingKey}/work-tasks`, {
    issue_type: issue.value, message: message.value.trim(), client_request_id: requestId.value,
  }, { signal, timeout: Math.min(timeoutMs, timeouts.task) })).data
  for (const file of [...images.value]) {
    await api.post<Attachment>(`/work-tasks/${savedTicket.value.id}/attachments`, file, {
      params: { file_name: file.name }, headers: { 'Content-Type': file.type }, signal, timeout: timeouts.noteSave,
    })
    images.value = images.value.filter(f => f !== file)
  }
  return savedTicket.value
}, { timeoutMs: timeouts.task + 5 * timeouts.noteSave })
function edited() { if (!savedTicket.value) requestId.value = crypto.randomUUID() }
async function submit() {
  if (!valid.value || create.pending.value) return
  const result = await create.run()
  if (result) {
    savedTicket.value = null; message.value = ''; images.value = []; edited(); emit('created', result)
  }
}
async function open() {
  if (!root.value) return
  root.value.open = true
  await nextTick()
  root.value?.querySelector('select')?.focus()
}
defineExpose({ open })
</script>
<template>
  <details ref="root" class="booking-ticket-panel">
    <summary>{{ t('workTaskUi.bookingTitle') }}</summary>
    <p class="muted">{{ t('workTaskUi.bookingHint') }}</p>
    <form @submit.prevent="submit">
      <label class="field-label" :for="`ticket-issue-${bookingKey}`">{{ t('ticketCompose.suggestion') }}</label>
      <select :id="`ticket-issue-${bookingKey}`" v-model="issue" :disabled="create.pending.value || !!savedTicket" @change="edited">
        <option value="contract">{{ t('ticketCompose.contract') }}</option><option value="cannot_send_rejection_letters">{{ t('ticketCompose.rejection') }}</option>
      </select>
      <label class="field-label" :for="`ticket-title-${bookingKey}`">{{ t('ticketCompose.title') }}</label>
      <input :id="`ticket-title-${bookingKey}`" :value="title" readonly />
      <label class="field-label" :for="`ticket-${bookingKey}`">{{ t('ticketCompose.content') }}</label>
      <textarea :id="`ticket-${bookingKey}`" v-model="message" lang="en" maxlength="2000" rows="5" required :placeholder="t('workTaskUi.placeholder')" @input="edited" :disabled="create.pending.value || !!savedTicket" />
      <p v-if="message.trim() && !valid" role="alert" class="field-error">{{ t('ticketCompose.englishRequired') }}</p>
      <TicketTranslation :disabled="create.pending.value || !!savedTicket" @apply="message = $event; edited()" />
      <StagedImages v-model="images" :disabled="create.pending.value || !!savedTicket" />
      <p v-if="savedTicket && !create.pending.value" role="status" class="booking-warning">{{ t('ticketCompose.imagesPending') }}</p>
      <button class="button primary" type="submit" :disabled="!valid || create.pending.value">{{ t(create.pending.value ? 'workTaskUi.creating' : savedTicket ? 'request_retry' : 'workTaskUi.create') }}</button>
    </form>
    <RequestStatus :state="create.state.value" :error="create.error.value" @retry="submit" />
    <p v-if="create.state.value === 'success'" role="status" class="ticket-success">{{ t('workTaskUi.created') }}</p>
  </details>
</template>
