<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { downloadReport, saveDownload } from '../utils/download'
import { timeouts } from '../config/timeouts'
import type { InvoiceReport } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
const { t } = useI18n(),
  month = ref('')
const period = () => (month.value ? month.value.slice(2).replace('-', '') : '')
const request = useRequest(
  async ({ signal, timeoutMs }) =>
    (
      await api.get<InvoiceReport>('/reports/invoices', {
        params: period() ? { period: period() } : {},
        signal,
        timeout: timeoutMs,
      })
    ).data,
  { timeoutMs: timeouts.list },
)
const report = computed(() => request.data.value)
async function load() {
  const value = await request.run()
  if (value) month.value = `20${value.period.slice(0, 2)}-${value.period.slice(2)}`
}
const exporting = useRequest(
  (ctx, period: string, format: string) =>
    downloadReport(ctx, '/export/invoices', { period, format }),
  { timeoutMs: timeouts.export },
)
async function download(format: string) {
  if (!report.value || exporting.pending.value) return
  const selected = report.value.period
  const blob = await exporting.run(selected, format)
  if (blob) saveDownload(blob, `invoices-${selected}.${format}`)
}
const fields = [
  'bookings',
  'with_invoice',
  'no_invoice',
  'not_declared',
  'invoice_total',
  'multi_invoice_bookings',
  'avg_per_booking',
  'max_per_booking',
] as const
const scale = computed(() =>
  Math.max(1, ...(report.value?.distribution ?? []).map((d) => d.bookings)),
)
onMounted(load)
</script>
<template>
  <section class="invoice-report-panel">
    <h2>{{ t('invoiceUi.report') }}</h2>
    <p class="muted">{{ t('invoiceUi.reportHint') }}</p>
    <form class="admin-form-actions" @submit.prevent="load">
      <label>{{ t('invoiceUi.period') }}<input v-model="month" type="month" required /></label
      ><button class="button" :disabled="request.pending.value">
        {{ t('invoiceUi.load') }}
      </button>
    </form>
    <RequestStatus
      :state="request.state.value"
      :error="request.error.value"
      @retry="load"
    /><RequestStatus :state="exporting.state.value" :error="exporting.error.value" />
    <template v-if="report"
      ><p>{{ report.period_label }}</p>
      <div class="report-metrics">
        <article v-for="field in fields" :key="field">
          <span>{{ t(`invoiceUi.${field}`) }}</span
          ><RouterLink
            v-if="field === 'not_declared'"
            :to="{
              name: 'summary',
              query: { invoice_state: 'unknown', period: month },
            }"
            ><strong>{{ report[field] }}</strong></RouterLink
          ><strong v-else>{{
            field === 'avg_per_booking' ? report[field].toFixed(2) : report[field]
          }}</strong>
        </article>
      </div>
      <h3>{{ t('invoiceUi.distribution') }}</h3>
      <div class="invoice-distribution" role="img" :aria-label="t('invoiceUi.distribution')">
        <div v-for="row in report.distribution" :key="row.invoices">
          <span>{{ row.invoices }}</span
          ><span
            class="invoice-bar"
            :style="{ height: `${(row.bookings / scale) * 100 + 2}px` }"
          ></span
          ><strong>{{ row.bookings }}</strong>
        </div>
      </div>
      <div class="admin-form-actions">
        <button
          type="button"
          class="button"
          :disabled="exporting.pending.value"
          @click="download('xlsx')"
        >
          {{ t('invoiceUi.exportXlsx') }}</button
        ><button
          type="button"
          class="button"
          :disabled="exporting.pending.value"
          @click="download('csv')"
        >
          {{ t('invoiceUi.exportCsv') }}
        </button>
      </div></template
    >
  </section>
</template>
