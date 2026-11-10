<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { useAuthStore } from '../stores/auth'
import { timeouts } from '../config/timeouts'
import { formatDateTime } from '../utils/dateTime'
import { downloadReport, saveDownload } from '../utils/download'
import type { PersonalDailyReport } from '../types/api.generated'
import RequestStatus from '../components/RequestStatus.vue'
import PageControls from '../components/PageControls.vue'
import StatusTag from '../components/StatusTag.vue'
import EmptyState from '../components/EmptyState.vue'
const { t } = useI18n(), auth = useAuthStore()
const day = ref(''), page = ref(1)
const request = useRequest(async ({ signal, timeoutMs }) => (await api.get<PersonalDailyReport>('/reports/mine/daily', {
  params: { date: day.value || undefined, page: page.value, size: 20 }, signal, timeout: timeoutMs,
})).data, { timeoutMs: timeouts.list, retry: true })
const report = computed(() => request.data.value)
const exporting = useRequest((ctx, day: string) => downloadReport(ctx, '/reports/mine/daily/export', { date: day }), { timeoutMs: timeouts.export })
async function load(reset = false) {
  if (reset) page.value = 1
  const value = await request.run()
  if (value) day.value = value.report_date
}
async function changePage(value: number) { page.value = value; await load() }
async function download() {
  if (!report.value || exporting.pending.value) return
  const selected = report.value.report_date, value = await exporting.run(selected)
  if (value) saveDownload(value, `my-daily-report-${selected}.xlsx`)
}
onMounted(() => load())
</script>
<template>
  <section class="page-shell personal-daily-report">
    <header class="page-heading summary-heading"><div><h1>{{ t('personalReportUi.title') }}</h1><p>{{ t('personalReportUi.intro') }}</p></div></header>
    <form class="workflow-controls" @submit.prevent="load(true)">
      <label>{{ t('opsUi.reportDate') }}<input v-model="day" type="date" required /></label>
      <button class="button" type="submit" :disabled="request.pending.value">{{ t('opsUi.loadReport') }}</button>
      <button class="button primary" type="button" :disabled="!report || exporting.pending.value" @click="download">{{ t('opsUi.downloadExcel') }}</button>
    </form>
    <RequestStatus :state="request.state.value" :error="request.error.value" @retry="load()" />
    <RequestStatus :state="exporting.state.value" :error="exporting.error.value" @retry="download" />
    <template v-if="report">
      <p class="muted">{{ report.agent.full_name }} · {{ report.report_date }} · {{ report.timezone }}</p>
      <div class="report-metrics">
        <article><span>{{ t('personalReportUi.bookings') }}</span><strong>{{ report.booking_count }}</strong></article>
        <article><span>{{ t('opsUi.notes') }}</span><strong>{{ report.note_count }}</strong></article>
        <article><span>{{ t('personalReportUi.done') }}</span><strong>{{ report.done_count }}</strong></article>
      </div>
      <p class="report-explanation">{{ t('personalReportUi.countHint') }}</p>
      <div v-if="report.items.length" class="booking-table-wrap"><table class="booking-table personal-report-table">
        <thead><tr><th>{{ t('bookingUi.booking') }}</th><th>{{ t('bookingUi.supplier') }}</th><th>{{ t('bookingUi.status') }}</th><th>{{ t('opsUi.notes') }}</th><th>{{ t('bookingUi.updatedAt') }}</th></tr></thead>
        <tbody><tr v-for="row in report.items" :key="row.booking_key"><td><RouterLink class="table-booking-link" :to="{ name: 'booking', params: { key: row.booking_key } }">{{ row.display_key }}</RouterLink></td><td>{{ row.supplier_name }}<small class="muted"> {{ row.station_code }}</small></td><td><StatusTag :status="row.last_status" /></td><td>{{ row.note_count }}</td><td>{{ formatDateTime(row.updated_at, auth.timezone) }}</td></tr></tbody>
      </table></div>
      <EmptyState v-else :title="t('personalReportUi.empty')" :description="t('personalReportUi.emptyHint')" />
      <PageControls :page="page" :size="20" :total="report.total" @change="changePage" />
    </template>
  </section>
</template>
