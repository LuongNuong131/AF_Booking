<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import { useAuthStore } from '../stores/auth'
import { formatDateTime } from '../utils/dateTime'
import { saveDownload, downloadReport } from '../utils/download'
import type { DailyReportDTO } from '../types/api.generated'
import RequestStatus from '../components/RequestStatus.vue'
import DailyBookingList from '../components/DailyBookingList.vue'
const route = useRoute(),
  router = useRouter(),
  { t } = useI18n(),
  auth = useAuthStore(),
  day = ref(String(route.query.date ?? ''))
const request = useRequest(
  async ({ signal, timeoutMs }) =>
    (
      await api.get<DailyReportDTO>('/reports/daily', {
        params: day.value ? { date: day.value } : {},
        signal,
        timeout: timeoutMs,
      })
    ).data,
  { timeoutMs: timeouts.export },
)
const report = computed(() => request.data.value)
const exporting = useRequest(
  (ctx, day: string) => downloadReport(ctx, '/reports/daily/export', { date: day }),
  { timeoutMs: timeouts.export },
)
async function load() {
  const result = await request.run()
  if (result) {
    day.value = result.report_date
    await router.replace({ name: 'daily-report', query: { date: day.value } })
  }
}
async function download() {
  if (!report.value || exporting.pending.value) return
  const selected = report.value.report_date
  const value = await exporting.run(selected)
  if (value) saveDownload(value, `daily-report-${selected}.xlsx`)
}
function print() {
  window.print()
}
onMounted(load)
</script>
<template>
  <section class="page-shell daily-report-view">
    <header class="page-heading">
      <p class="page-eyebrow">{{ t('app.workspace') }}</p>
      <h1>{{ t('opsUi.dailyTitle') }}</h1>
      <p>{{ t('opsUi.dailyHint') }}</p>
    </header>
    <form class="daily-report-controls" @submit.prevent="load">
      <label>{{ t('opsUi.reportDate') }}<input v-model="day" type="date" required /></label
      ><button type="submit" class="button" :disabled="request.pending.value">
        {{ t('opsUi.loadReport') }}</button
      ><button type="button" class="button" :disabled="!report" @click="print">
        {{ t('opsUi.print') }}</button
      ><button
        type="button"
        class="button primary"
        :disabled="!report || exporting.pending.value"
        @click="download"
      >
        {{ t('opsUi.downloadExcel') }}
      </button>
    </form>
    <RequestStatus
      :state="request.state.value"
      :error="request.error.value"
      @retry="load"
    /><RequestStatus
      :state="exporting.state.value"
      :error="exporting.error.value"
      @retry="download"
    /><template v-if="report"
      ><p>
        {{ report.report_date }} · {{ report.timezone }} ·
        {{
          t('opsUi.generated', {
            at: formatDateTime(report.generated_at, auth.timezone),
          })
        }}
      </p>
      <p v-if="report.provisional" class="muted">
        {{ t('opsUi.provisional') }}
      </p>
      <div class="report-metrics">
        <article>
          <span>{{ t('opsUi.notes') }}</span
          ><strong>{{ report.note_count }}</strong>
        </article>
        <article>
          <span>{{ t('opsUi.newBookings') }}</span
          ><strong>{{ report.new_booking_count }}</strong>
        </article>
        <article>
          <span>{{ t('opsUi.done') }}</span
          ><strong>{{ report.done_count }}</strong>
        </article>
        <article>
          <span>{{ t('opsUi.overdueTasks') }}</span
          ><strong>{{ report.overdue_task_count }}</strong>
        </article>
      </div>
      <h2>{{ t('invoiceUi.doneNotDeclared') }}</h2>
      <DailyBookingList :rows="report.done_not_declared ?? []" />
      <h2>{{ t('opsUi.statusDistribution') }}</h2>
      <ul class="daily-status-list">
        <li v-for="row in report.status_distribution" :key="row.code">
          {{ row.label }} <strong>{{ row.count }}</strong>
        </li>
      </ul>
      <h2>{{ t('opsUi.byAgent') }}</h2>
      <div class="booking-table-wrap">
        <table class="booking-table">
          <thead>
            <tr>
              <th>{{ t('bookingUi.agent') }}</th>
              <th>{{ t('opsUi.notes') }}</th>
              <th>{{ t('opsUi.done') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in report.agents" :key="row.id">
              <td>{{ row.full_name }}</td>
              <td>{{ row.note_count }}</td>
              <td>{{ row.done_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <h2>{{ t('opsUi.byStation') }}</h2>
      <div class="booking-table-wrap">
        <table class="booking-table">
          <thead>
            <tr>
              <th>{{ t('bookingUi.station') }}</th>
              <th>{{ t('bookingUi.type') }}</th>
              <th>{{ t('opsUi.notes') }}</th>
              <th>{{ t('opsUi.done') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in report.stations"
              :key="`${row.station_code}:${row.supplier_type}`"
            >
              <td>{{ row.station_code }}</td>
              <td>{{ t(`supplier_types.${row.supplier_type}`) }}</td>
              <td>{{ row.note_count }}</td>
              <td>{{ row.done_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <template
        v-for="kind in ['stale', 'open_rejection_parking', 'repeated'] as const"
        :key="kind"
        ><h2>{{ t(`opsUi.${kind}`) }} ({{ report[kind].length }})</h2>
        <DailyBookingList :rows="report[kind]" /></template
    ></template>
  </section>
</template>
