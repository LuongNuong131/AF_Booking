<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { formatDateTime } from '../utils/dateTime'
import type { MonthlyBookingResult, MonthlyBookingStatus } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
const { t } = useI18n()
const status = useRequest(async ({ signal }) => (await api.get<MonthlyBookingStatus>('/admin/bookings/monthly', { signal })).data, { timeoutMs: 10000, retry: true })
const run = useRequest(async ({ signal }) => (await api.post<MonthlyBookingResult>('/admin/bookings/monthly/run', {}, { signal, timeout: 125000 })).data, { timeoutMs: 125000 })
async function catchUp() {
  if (run.pending.value) return
  if (await run.run()) await status.run()
}
onMounted(() => { void status.run() })
defineExpose({ refresh: () => status.run() })
</script>
<template>
  <section class="monthly-panel">
    <div>
      <h2>{{ t('monthlyUi.title') }}</h2>
      <p>{{ t('monthlyUi.rule') }}</p>
    </div>
    <RequestStatus :state="status.state.value" :error="status.error.value" @retry="status.run()" />
    <template v-if="status.data.value">
      <dl class="monthly-facts">
        <div><dt>{{ t('monthlyUi.state') }}</dt><dd>{{ t(status.data.value.enabled ? 'monthlyUi.enabled' : 'monthlyUi.disabled') }}</dd></div>
        <div><dt>{{ t('monthlyUi.folders') }}</dt><dd>{{ status.data.value.active_folders }}</dd></div>
        <div><dt>{{ t('monthlyUi.due') }}</dt><dd>{{ status.data.value.due_period }}</dd></div>
        <div><dt>{{ t('monthlyUi.next') }}</dt><dd>{{ formatDateTime(status.data.value.next_run_at, status.data.value.timezone) }}</dd></div>
      </dl>
      <p>{{ t('monthlyUi.pending', { count: status.data.value.pending_folders }) }}</p>
      <p v-if="!status.data.value.external_trigger_configured" class="monthly-guidance">{{ t('monthlyUi.freeHint') }}</p>
      <div class="import-actions">
        <button type="button" class="button" :disabled="run.pending.value || !status.data.value.enabled" @click="catchUp">{{ t('monthlyUi.catchUp') }}</button>
        <button type="button" class="text-button" :disabled="status.pending.value" @click="status.run()">{{ t('bookingUi.refresh') }}</button>
      </div>
      <p v-if="run.data.value" role="status">{{ t('monthlyUi.created', { count: run.data.value.created, period: run.data.value.period }) }}</p>
      <RequestStatus :state="run.state.value" :error="run.error.value" />
    </template>
  </section>
</template>
