<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import type { Page, WorkTaskItem } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
const props = defineProps<{ bookingKey: string }>()
const { t } = useI18n(), message = ref(''), requestId = ref(crypto.randomUUID())
const list = useRequest(async ({ signal, timeoutMs }) => (await api.get<Page<WorkTaskItem>>('/work-tasks', {
  params: { booking_key: props.bookingKey, status: 'pending', size: 5 }, signal, timeout: timeoutMs,
})).data, { timeoutMs: timeouts.list })
const create = useRequest(async ({ signal, timeoutMs }, body: { message: string; client_request_id: string }) =>
  (await api.post<WorkTaskItem>(`/bookings/${props.bookingKey}/work-tasks`, body, { signal, timeout: timeoutMs })).data,
{ timeoutMs: timeouts.task })
function edited() { requestId.value = crypto.randomUUID() }
async function submit() {
  if (!message.value.trim() || create.pending.value) return
  if (await create.run({ message: message.value.trim(), client_request_id: requestId.value })) {
    message.value = ''; edited(); await list.run()
  }
}
function toggle(event: Event) { if ((event.target as HTMLDetailsElement).open) void list.run() }
</script>
<template>
  <details class="booking-ticket-panel" @toggle="toggle">
    <summary>{{ t('workTaskUi.bookingTitle') }}</summary>
    <p class="muted">{{ t('workTaskUi.bookingHint') }}</p>
    <form @submit.prevent="submit"><label class="field-label" :for="`ticket-${bookingKey}`">{{ t('workTaskUi.issue') }}</label>
      <textarea :id="`ticket-${bookingKey}`" v-model="message" maxlength="2000" rows="3" required :placeholder="t('workTaskUi.placeholder')" @input="edited" :disabled="create.pending.value" />
      <button class="button primary" type="submit" :disabled="!message.trim() || create.pending.value">{{ t(create.pending.value ? 'workTaskUi.creating' : 'workTaskUi.create') }}</button>
    </form>
    <RequestStatus :state="create.state.value" :error="create.error.value" @retry="submit" />
    <p v-if="create.state.value === 'success'" role="status" class="ticket-success">{{ t('workTaskUi.created') }}</p>
    <RequestStatus :state="list.state.value" :error="list.error.value" @retry="list.run" />
    <ul v-if="list.data.value?.items.length" class="ticket-mini-list"><li v-for="item in list.data.value.items" :key="item.id"><strong>#{{ item.id }}</strong> {{ item.message }}</li></ul>
    <RouterLink class="text-button" :to="{ name: 'tickets', query: { booking_key: bookingKey } }">{{ t('workTaskUi.viewTickets') }}</RouterLink>
  </details>
</template>
