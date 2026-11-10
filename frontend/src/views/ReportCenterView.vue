<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useRequest } from '../composables/useRequest'
import { useViewRefresh } from '../composables/useViewRefresh'
import { timeouts } from '../config/timeouts'
import { zonedToday } from '../utils/summaryFilters'
import { formatDateTime } from '../utils/dateTime'
import { downloadReport, saveDownload } from '../utils/download'
import type { ReportCenter, ReportFilters, ReportOptions, AgentSummary, Status } from '../types/api.generated'
import RequestStatus from '../components/RequestStatus.vue'
import PageControls from '../components/PageControls.vue'
import EmptyState from '../components/EmptyState.vue'
import StatusTag from '../components/StatusTag.vue'
import InvoiceBadge from '../components/InvoiceBadge.vue'
import BaseIcon from '../components/BaseIcon.vue'
import InvoiceReportPanel from '../components/InvoiceReportPanel.vue'
const props = defineProps<{ personal?: boolean }>()
const { t } = useI18n(), auth = useAuthStore(), route = useRoute(), router = useRouter()
const supervisor = computed(() => ['admin', 'qc'].includes(auth.user?.role ?? ''))
let today = zonedToday(auth.timezone)
const reportZone = ref(auth.timezone)
const page = ref(1), tab = ref<'agents' | 'statuses' | 'stations' | 'classifications'>('agents'), selectedPreset = ref('today')
const filters = reactive({ date_from: String(route.query.date_from || today), date_to: String(route.query.date_to || today), scope: (props.personal || !supervisor.value ? 'mine' : route.query.scope === 'mine' ? 'mine' : 'team') as 'mine' | 'team', agent_id: String(route.query.agent_id || ''), station: String(route.query.station || ''), supplier_type: String(route.query.supplier_type || ''), status_code: String(route.query.status_code || ''), invoice_state: String(route.query.invoice_state || '') })
const applied = ref<ReportFilters | null>(null), agents = ref<AgentSummary[]>([]), statuses = ref<Status[]>([])
const params = () => Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== '').map(([k, v]) => [k, k === 'agent_id' ? Number(v) : v])) as ReportFilters
const valid = computed(() => !!filters.date_from && !!filters.date_to && filters.date_to >= filters.date_from && (Date.parse(filters.date_to)-Date.parse(filters.date_from))/86400000 <= 365)
const request = useRequest(async (ctx, query: ReportFilters, p: number) => (await api.get<ReportCenter>('/reports/center', { params: { ...query, page: p, size: 20 }, signal: ctx.signal, timeout: ctx.timeoutMs })).data, { timeoutMs: timeouts.export, retry: true })
const exporting = useRequest((ctx, query: ReportFilters, format: 'xlsx' | 'csv') => downloadReport(ctx, '/reports/center/export', Object.fromEntries(Object.entries({ ...query, format }).filter(([, v]) => v !== null).map(([k, v]) => [k, String(v)]))), { timeoutMs: timeouts.export })
const report = computed(() => request.data.value)
const dirty = computed(() => !!applied.value && Object.entries(params()).some(([k, v]) => v !== applied.value?.[k as keyof ReportFilters]))
async function load(reset = true) {
  if (reset && !valid.value) return
  const query = reset || !applied.value ? params() : applied.value
  if (reset) page.value = 1
  const value = await request.run(query, page.value)
  if (value) {
    applied.value = value.filters
    await router.replace({ query: Object.fromEntries(Object.entries(query).filter(([, v]) => v !== undefined && v !== null).map(([k, v]) => [k, String(v)])) })
  }
}
async function download(format: 'xlsx' | 'csv') {
  if (!applied.value || exporting.pending.value) return
  const snapshot = { ...applied.value }, value = await exporting.run(snapshot, format)
  if (value) saveDownload(value, `af-booking-${snapshot.scope}-${snapshot.date_from}-${snapshot.date_to}.${format}`)
}
function preset(value: string) {
  selectedPreset.value = value
  const day = new Date(`${today}T12:00:00Z`), iso = (date: Date) => date.toISOString().slice(0, 10)
  filters.date_to = today
  if (value === 'yesterday') { day.setUTCDate(day.getUTCDate()-1); filters.date_to = iso(day) }
  if (value === 'week') day.setUTCDate(day.getUTCDate()-6)
  if (value === 'month') day.setUTCDate(1)
  filters.date_from = iso(day)
  void load()
}
const completion = computed(() => report.value?.bookings ? Math.round(report.value.done / report.value.bookings * 100) : 0)
const trendMax = computed(() => Math.max(1, ...report.value?.trend.map(r => r.updates) ?? [1]))
const trendPoints = computed(() => report.value?.trend.map((r, i, list) => `${24+i*952/Math.max(1,list.length-1)},${180-r.updates/trendMax.value*150}`).join(' ') ?? '')
useViewRefresh(() => load(false))
onMounted(async () => {
  const options = await api.get<ReportOptions>('/reports/center/options').catch(() => null)
  if (options) {
    today = options.data.today; reportZone.value = options.data.timezone
    if (!route.query.date_from) filters.date_from = today
    if (!route.query.date_to) filters.date_to = today
  }
  void load()
  const directory = await Promise.allSettled([api.get<AgentSummary[]>('/users/lookup', { params: { limit: 50 } }), api.get<Status[]>('/statuses')])
  if (directory[0].status === 'fulfilled') agents.value = directory[0].value.data
  if (directory[1].status === 'fulfilled') statuses.value = directory[1].value.data
})
</script>
<template>
  <section class="report-center page-shell">
    <header class="page-heading report-center-heading"><div><span class="report-kicker">AF BOOKING · {{ t('reportUi.operations') }}</span><h1>{{ t(props.personal || !supervisor ? 'reportUi.personalTitle' : 'reportUi.title') }}</h1><p>{{ t('reportUi.intro') }}</p></div><div class="report-export-actions"><button class="button primary" :disabled="!report || exporting.pending.value" @click="download('xlsx')"><BaseIcon name="chart" />{{ t(exporting.pending.value ? 'reportUi.exporting' : 'reportUi.excel') }}</button><button class="button" :disabled="!report || exporting.pending.value" @click="download('csv')">CSV</button></div></header>
    <form class="report-control-panel" @submit.prevent="load()"><div class="report-presets"><button v-for="value in ['today', 'yesterday', 'week', 'month']" :key="value" class="button" :class="{ selected: selectedPreset === value }" type="button" @click="preset(value)">{{ t(`reportUi.${value}`) }}</button><span>{{ t('reportUi.businessZone') }} · {{ report?.timezone ?? reportZone }}</span></div><div class="report-filter-grid">
      <label>{{ t('bookingUi.dateFrom') }}<input v-model="filters.date_from" type="date" required @input="selectedPreset = ''" /></label><label>{{ t('bookingUi.dateTo') }}<input v-model="filters.date_to" type="date" required @input="selectedPreset = ''" /></label>
      <label v-if="supervisor && !personal">{{ t('reportUi.scope') }}<select v-model="filters.scope" @change="filters.agent_id = ''"><option value="team">{{ t('reportUi.team') }}</option><option value="mine">{{ t('reportUi.mine') }}</option></select></label>
      <label v-if="supervisor && filters.scope === 'team'">{{ t('bookingUi.agent') }}<select v-model="filters.agent_id"><option value="">{{ t('bookingUi.allAgents') }}</option><option v-for="agent in agents" :key="agent.id" :value="String(agent.id)">{{ agent.full_name }}</option></select></label>
      <label>{{ t('bookingUi.station') }}<input v-model="filters.station" maxlength="4" @input="filters.station = filters.station.toUpperCase()" /></label><label>{{ t('bookingUi.type') }}<select v-model="filters.supplier_type"><option value="">{{ t('bookingUi.allTypes') }}</option><option v-for="kind in ['unclassified', 'hotel', 'transportation']" :key="kind" :value="kind">{{ t(`supplier_types.${kind}`) }}</option></select></label><label>{{ t('bookingUi.status') }}<select v-model="filters.status_code"><option value="">{{ t('bookingUi.allStatuses') }}</option><option v-for="status in statuses" :key="status.code" :value="status.code">{{ status.label }}</option></select></label><label>{{ t('reportUi.invoiceDeclaration') }}<select v-model="filters.invoice_state"><option value="">{{ t('adminUi.all') }}</option><option v-for="state in ['unknown', 'has_invoice', 'no_invoice']" :key="state" :value="state">{{ t(`reportUi.invoice.${state}`) }}</option></select></label>
    </div><div class="report-filter-footer"><p v-if="!valid" role="alert" class="field-error">{{ t('reportUi.invalidRange') }}</p><p v-else class="muted">{{ t(dirty ? 'reportUi.unapplied' : 'reportUi.rangeHint') }}</p><button type="submit" class="button primary" :disabled="!valid || request.pending.value">{{ t('reportUi.apply') }}</button></div></form>
    <RequestStatus :state="request.state.value" :error="request.error.value" @retry="load()" /><RequestStatus :state="exporting.state.value" :error="exporting.error.value" @retry="download('xlsx')" />
    <template v-if="report"><div class="report-stamp"><span>{{ t('reportUi.preparedFor', { name: report.requested_by }) }}</span><span>{{ formatDateTime(report.generated_at, report.timezone) }}</span></div>
      <div class="report-kpis"><article><span>{{ t('reportUi.bookings') }}</span><strong>{{ report.bookings.toLocaleString() }}</strong><small>{{ t('reportUi.unique') }}</small></article><article><span>{{ t('reportUi.updates') }}</span><strong>{{ report.updates.toLocaleString() }}</strong><small>{{ t('reportUi.updatesHint') }}</small></article><article class="positive"><span>{{ t('reportUi.done') }}</span><strong>{{ report.done.toLocaleString() }} <small>{{ completion }}%</small></strong><small>{{ t('reportUi.finalStatus') }}</small></article><article><span>{{ t('reportUi.attention') }}</span><strong>{{ report.unclassified + report.undeclared_invoices }}</strong><small>{{ t('reportUi.attentionHint', { types: report.unclassified, invoices: report.undeclared_invoices }) }}</small></article></div>
      <div class="report-analysis-grid"><article class="report-section"><header><h2>{{ t('reportUi.trend') }}</h2><span class="muted">{{ t('reportUi.updates') }}</span></header><svg v-if="report.bookings && report.trend.length > 1" class="report-trend" viewBox="0 0 1000 210" role="img" :aria-label="t('reportUi.trend')"><line x1="24" y1="180" x2="976" y2="180" stroke="var(--line)" /><polygon :points="`24,180 ${trendPoints} 976,180`" fill="var(--primary-soft)" /><polyline :points="trendPoints" fill="none" stroke="var(--primary)" stroke-width="3" /><circle v-for="(day, index) in report.trend" :key="day.key" :cx="24+index*952/Math.max(1,report.trend.length-1)" :cy="180-day.updates/trendMax*150" r="4" fill="var(--primary)"><title>{{ day.label }} · {{ day.updates }}</title></circle></svg><div v-else-if="report.bookings" class="report-single-day"><strong>{{ report.updates }}</strong><span>{{ t('reportUi.updates') }}</span><small>{{ report.filters.date_from }}</small></div><EmptyState v-else :title="t('reportUi.empty')" /><div class="trend-range"><span>{{ report.filters.date_from }}</span><span>{{ report.filters.date_to }}</span></div><details class="report-methodology"><summary>{{ t('reportUi.trendData') }}</summary><div class="admin-table-wrap"><table class="admin-table"><thead><tr><th>{{ t('opsUi.reportDate') }}</th><th>{{ t('reportUi.bookings') }}</th><th>{{ t('reportUi.updates') }}</th><th>{{ t('reportUi.done') }}</th></tr></thead><tbody><tr v-for="day in report.trend" :key="day.key"><td>{{ day.label }}</td><td>{{ day.bookings }}</td><td>{{ day.updates }}</td><td>{{ day.done }}</td></tr></tbody></table></div></details></article>
      <article class="report-section"><header><h2>{{ t('reportUi.breakdown') }}</h2></header><div class="report-breakdown-tabs"><button v-for="value in ['agents', 'statuses', 'stations', 'classifications'] as const" :key="value" type="button" :aria-pressed="tab === value" :class="{ selected: tab === value }" @click="tab = value">{{ t(`reportUi.${value}`) }}</button></div><div v-if="report[tab].length" class="report-breakdown-list"><div v-for="row in report[tab]" :key="row.key"><div><strong>{{ tab === 'classifications' ? t(`supplier_types.${row.key}`) : row.label }}</strong><span>{{ row.bookings }} {{ t('reportUi.bookingsShort') }} · {{ row.updates }} {{ t('reportUi.updatesShort') }}</span></div><progress :value="row.bookings" :max="report.bookings" :aria-label="row.label" /><small>{{ t('reportUi.done') }}: {{ row.done }}</small></div></div><EmptyState v-else :title="t('reportUi.empty')" /></article></div>
      <article class="report-section report-detail"><header><div><h2>{{ t('reportUi.detail') }}</h2><p class="muted">{{ t('reportUi.detailHint') }}</p></div><span class="report-total">{{ report.total.toLocaleString() }} {{ t('reportUi.bookingsShort') }}</span></header><div v-if="report.items.length" class="admin-table-wrap"><table class="admin-table report-detail-table"><thead><tr><th>{{ t('bookingUi.booking') }}</th><th>{{ t('bookingUi.supplier') }}</th><th>{{ t('bookingUi.agent') }}</th><th>{{ t('reportUi.finalStatus') }}</th><th>{{ t('reportUi.updates') }}</th><th>{{ t('reportUi.invoiceDeclaration') }}</th><th>{{ t('bookingUi.updatedAt') }}</th></tr></thead><tbody><tr v-for="row in report.items" :key="row.booking_key"><td><RouterLink class="table-booking-link" :to="{ name: 'booking', params: { key: row.booking_key } }">{{ row.display_key }}</RouterLink><small>{{ row.period }} · {{ row.station }}</small></td><td>{{ row.supplier_name }}<small>{{ t(`supplier_types.${row.supplier_type}`) }}</small></td><td>{{ row.agent.full_name }}</td><td><StatusTag :status="{ code: row.status_code, label: row.status_label }" /><details v-if="row.note" class="report-note"><summary>{{ t('reportUi.viewNote') }}</summary><p>{{ row.note }}</p></details></td><td>{{ row.note_count }}</td><td><InvoiceBadge :state="row.invoice_state as 'unknown' | 'has_invoice' | 'no_invoice'" :count="row.invoice_count" :preview="row.invoices" :done="row.is_done" /></td><td>{{ formatDateTime(row.updated_at, report.timezone) }}</td></tr></tbody></table></div><EmptyState v-else :title="t('reportUi.empty')" :description="t('common.noRecordsHint')" /><PageControls :page="page" :size="20" :total="report.total" @change="page = $event; load(false)" /></article>
      <details class="report-methodology"><summary>{{ t('reportUi.methodology') }}</summary><p>{{ t('reportUi.counting') }}</p><p>{{ t('reportUi.metadata') }}</p><p>{{ t('reportUi.exportHint') }}</p></details>
      <InvoiceReportPanel v-if="supervisor && !personal" />
      <nav v-if="supervisor" class="report-related"><RouterLink class="button" :to="{ name: 'daily-report' }">{{ t('opsUi.dailyTitle') }}</RouterLink><RouterLink class="button" :to="{ name: 'tickets' }">{{ t('workTaskUi.nav') }}</RouterLink></nav>
    </template>
  </section>
</template>
