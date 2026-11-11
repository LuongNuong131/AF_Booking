<script setup lang="ts">
import { computed, reactive } from 'vue'
import { ElDialog } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import { englishTicket, ticketTitles, type IssueType } from '../utils/ticket'
import type { WorkTaskItem, WorkTaskUpdate } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
const props = defineProps<{ ticket: WorkTaskItem }>()
const emit = defineEmits<{ saved: [ticket: WorkTaskItem]; close: [] }>()
const { t } = useI18n()
const form = reactive({ title: props.ticket.title, message: props.ticket.message,
  issue_type: props.ticket.issue_type ?? '', status: props.ticket.status,
  handling_note: props.ticket.handling_note ?? '' })
const valid = computed(() => !!form.title.trim() && englishTicket(form.message.trim()))
function suggestTitle() { if (form.issue_type) form.title = `${ticketTitles[form.issue_type as IssueType]} - ${props.ticket.booking_key}` }
const mutation = useRequest(async ({ signal, timeoutMs }) => {
  const body: WorkTaskUpdate = {
    expected_token: props.ticket.edit_token, title: form.title.trim(), message: form.message.trim(),
    issue_type: form.issue_type ? form.issue_type as IssueType : null,
    status: form.status as 'pending' | 'handled',
    handling_note: form.status === 'handled' ? form.handling_note.trim() || null : null,
  }
  return (await api.patch<WorkTaskItem>(`/work-tasks/${props.ticket.id}`, body, { signal, timeout: timeoutMs })).data
}, { timeoutMs: timeouts.task })
async function save() { if (!valid.value || mutation.pending.value) return; const result = await mutation.run(); if (result) emit('saved', result) }
</script>
<template>
  <ElDialog :model-value="true" :title="t('ticketAdmin.edit')" width="720px" :close-on-click-modal="!mutation.pending.value" :close-on-press-escape="!mutation.pending.value" :show-close="!mutation.pending.value" @update:model-value="!mutation.pending.value && emit('close')">
    <form class="admin-edit-form ticket-edit-form" @submit.prevent="save">
      <p class="muted">#{{ ticket.id }} · {{ ticket.display_key }} · {{ ticket.creator.full_name }}</p>
      <label>{{ t('ticketCompose.suggestion') }}<select :aria-label="t('ticketCompose.suggestion')" v-model="form.issue_type" :disabled="mutation.pending.value" @change="suggestTitle"><option value="">{{ t('ticketAdmin.unclassified') }}</option><option value="contract">{{ t('ticketCompose.contract') }}</option><option value="cannot_send_rejection_letters">{{ t('ticketCompose.rejection') }}</option></select></label>
      <label>{{ t('ticketCompose.title') }}<input v-model="form.title" required maxlength="255" :disabled="mutation.pending.value" /></label>
      <button v-if="form.issue_type" type="button" class="text-button" :disabled="mutation.pending.value" @click="suggestTitle">{{ t('ticketAdmin.suggestTitle') }}</button>
      <label>{{ t('ticketCompose.content') }}<textarea v-model="form.message" lang="en" required maxlength="2000" rows="6" :disabled="mutation.pending.value" /></label>
      <p v-if="form.message.trim() && !englishTicket(form.message)" class="field-error" role="alert">{{ t('ticketCompose.englishRequired') }}</p>
      <label>{{ t('workTaskUi.status') }}<select :aria-label="t('workTaskUi.status')" v-model="form.status" :disabled="mutation.pending.value"><option value="pending">{{ t('workTaskUi.pending') }}</option><option value="handled">{{ t('workTaskUi.handled') }}</option></select></label>
      <label v-if="form.status === 'handled'">{{ t('workTaskUi.handlingNote') }}<textarea v-model="form.handling_note" maxlength="2000" rows="3" :disabled="mutation.pending.value" /></label>
      <p v-if="mutation.error.value?.code === 'VERSION_CONFLICT'" class="field-error" role="alert">{{ t('ticketAdmin.changed') }}</p>
      <RequestStatus v-else :state="mutation.state.value" :error="mutation.error.value" @retry="save" />
      <div class="admin-form-actions"><button type="button" class="button" :disabled="mutation.pending.value" @click="emit('close')">{{ t('folderUi.cancel') }}</button><button type="submit" class="button primary" :disabled="!valid || mutation.pending.value">{{ t('dataUi.save') }}</button></div>
    </form>
  </ElDialog>
</template>
