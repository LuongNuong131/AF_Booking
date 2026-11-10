<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { useViewRefresh } from '../composables/useViewRefresh'
import { timeouts } from '../config/timeouts'
import { downloadDaily, saveDownload } from '../utils/download'
import type { AgentSummary, PerformanceReport, Status } from '../types/api.generated'
import InvoiceReportPanel from '../components/InvoiceReportPanel.vue'
import RequestStatus from '../components/RequestStatus.vue'
import { formatDateTime } from '../utils/dateTime'
const PerformanceCharts = defineAsyncComponent(
  () => import('../components/PerformanceCharts.vue'),
)
const { t } = useI18n(),
  filters = reactive({ period: 'day', date_from: '', date_to: '' }),
  exportDate = ref(''),
  format = ref('xlsx'),
  agent = ref(''),
  status = ref('')
const request = useRequest(
  async ({ signal, timeoutMs }) =>
    (
      await api.get<PerformanceReport>('/reports/performance', {
        params: Object.fromEntries(Object.entries(filters).filter(([, v]) => v)),
        signal,
        timeout: timeoutMs,
      })
    ).data,
  { timeoutMs: timeouts.list, retry: true },
)
const directory = useRequest(
  async ({ signal, timeoutMs }) =>
    (
      await api.get<AgentSummary[]>('/users/lookup', {
        params: { limit: 50 },
        signal,
        timeout: timeoutMs,
      })
    ).data,
  { timeoutMs: timeouts.list, retry: true },
)
const statuses = useRequest(
  async ({ signal, timeoutMs }) =>
    (await api.get<Status[]>('/statuses', { signal, timeout: timeoutMs })).data,
  { timeoutMs: timeouts.list, retry: true },
)
const exporting = useRequest(
  (ctx) =>
    downloadDaily(ctx, {
      date: exportDate.value,
      format: format.value,
      ...(agent.value ? { agent_id: agent.value } : {}),
      ...(status.value ? { status_code: status.value } : {}),
    }),
  { timeoutMs: timeouts.export },
)
const report = computed(() => request.data.value),
  stale = computed(() => report.value?.stale_by_user.reduce((sum, r) => sum + r.count, 0) ?? 0),
  overdue = computed(
    () => report.value?.overdue_tasks_by_user.reduce((sum, r) => sum + r.count, 0) ?? 0,
  )
async function load() {
  const value = await request.run()
  if (value) {
    filters.date_from = value.date_from
    filters.date_to = value.date_to
    if (!exportDate.value) exportDate.value = value.date_to
  }
}
function periodChanged() {
  filters.date_from = ''
  filters.date_to = ''
  void load()
}
async function exportFile() {
  if (exporting.pending.value || !exportDate.value) return
  const blob = await exporting.run()
  if (blob) saveDownload(blob, `daily-record-${exportDate.value}.${format.value}`)
}
onMounted(() => {
  void load()
  void directory.run()
  void statuses.run()
})
useViewRefresh(load)
</script>
<template>
  <section class="reports-view">
    <header class="page-heading">
      <p class="page-eyebrow">{{ t('app.workspace') }}</p>
      <h1>{{ t('pages.reportsTitle') }}</h1>
      <RouterLink class="button" :to="{ name: 'daily-report' }">{{
        t('opsUi.dailyTitle')
      }}</RouterLink>
      <RouterLink class="button" :to="{ name: 'my-daily-report' }">{{ t('personalReportUi.title') }}</RouterLink>
      <p>{{ t('adminUi.reportIntro') }}</p>
    </header>

    <InvoiceReportPanel />
    <form class="admin-filters" @submit.prevent="load">
      <label
        >{{ t('adminUi.period')
        }}<select
          :aria-label="t('adminUi.period')"
          v-model="filters.period"
          @change="periodChanged"
        >
          <option v-for="value in ['day', 'week', 'month']" :key="value" :value="value">
            {{ t(`adminUi.${value}`) }}
          </option>
        </select></label
      ><label
        >{{ t('bookingUi.dateFrom') }}<input v-model="filters.date_from" type="date" /></label
      ><label>{{ t('bookingUi.dateTo') }}<input v-model="filters.date_to" type="date" /></label
      ><button type="submit" class="button">
        {{ t('bookingUi.refresh') }}
      </button>
    </form>
    <RequestStatus
      :state="request.state.value"
      :error="request.error.value"
      @retry="load"
    /><template v-if="report"
      ><p class="report-asof">
        {{ report.timezone }} ·
        {{
          t('adminUi.asOf', {
            date: formatDateTime(report.generated_at, report.timezone),
          })
        }}
      </p>
      <div class="report-metrics">
        <article
          v-for="metric in [
            { key: 'notes', value: report.note_count },
            { key: 'done', value: report.done_count },
            { key: 'stale', value: stale },
            { key: 'overdueTasks', value: overdue },
          ]"
          :key="metric.key"
        >
          <span>{{ t(`adminUi.${metric.key}`) }}</span
          ><strong>{{ metric.value }}</strong>
        </article>
      </div>
      <PerformanceCharts :report="report" />
      <div class="report-tables">
        <section>
          <h2>{{ t('adminUi.performance') }}</h2>
          <table class="admin-table">
            <thead>
              <tr>
                <th>{{ t('bookingUi.agent') }}</th>
                <th>{{ t('adminUi.notes') }}</th>
                <th>{{ t('status_labels.done') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in report.users" :key="row.agent?.id ?? 0">
                <td>{{ row.agent?.full_name || t('adminUi.unassigned') }}</td>
                <td>{{ row.note_count }}</td>
                <td>{{ row.done_count }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <section>
          <h2>{{ t('adminUi.statusDistribution') }}</h2>
          <table class="admin-table">
            <tbody>
              <tr v-for="row in report.statuses" :key="row.status?.code ?? ''">
                <td>{{ row.status?.label || t('common.unknown') }}</td>
                <td>{{ row.count }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <section>
          <h2>{{ t('adminUi.stale') }}</h2>
          <table class="admin-table">
            <tbody>
              <tr v-for="row in report.stale_by_user" :key="row.agent?.id ?? 0">
                <td>{{ row.agent?.full_name || t('adminUi.unassigned') }}</td>
                <td>{{ row.count }}</td>
              </tr>
            </tbody>
          </table>
          <table class="admin-table">
            <tbody>
              <tr v-for="row in report.stale_by_status" :key="row.status?.code ?? ''">
                <td>{{ row.status?.label || t('common.unknown') }}</td>
                <td>{{ row.count }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <section>
          <h2>{{ t('adminUi.overdueTasks') }}</h2>
          <p class="muted">{{ t('adminUi.taskPrivacy') }}</p>
          <table class="admin-table">
            <tbody>
              <tr v-for="row in report.overdue_tasks_by_user" :key="row.agent?.id ?? 0">
                <td>{{ row.agent?.full_name || t('adminUi.unassigned') }}</td>
                <td>{{ row.count }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div></template
    >
    <section class="daily-export">
      <h2>{{ t('adminUi.dailyExport') }}</h2>

      <form class="admin-filters" @submit.prevent="exportFile">
        <label>{{ t('adminUi.date') }}<input v-model="exportDate" type="date" required /></label
        ><label
          >{{ t('bookingUi.agent')
          }}<select :aria-label="t('bookingUi.agent')" v-model="agent">
            <option value="">{{ t('bookingUi.allAgents') }}</option>
            <option
              v-for="user in directory.data.value ?? []"
              :key="user.id"
              :value="String(user.id)"
            >
              {{ user.full_name }}
            </option>
          </select></label
        ><label
          >{{ t('bookingUi.status')
          }}<select :aria-label="t('bookingUi.status')" v-model="status">
            <option value="">{{ t('bookingUi.allStatuses') }}</option>
            <option v-for="item in statuses.data.value ?? []" :key="item.id" :value="item.code">
              {{ item.label }}
            </option>
          </select></label
        ><label
          >{{ t('adminUi.format')
          }}<select :aria-label="t('adminUi.format')" v-model="format">
            <option value="xlsx">XLSX</option>
            <option value="csv">CSV</option>
          </select></label
        ><button type="submit" class="button primary" :disabled="exporting.pending.value">
          {{ t(exporting.pending.value ? 'adminUi.exporting' : 'adminUi.download') }}
        </button>
      </form>
      <RequestStatus
        :state="exporting.state.value"
        :error="exporting.error.value"
        can-cancel
        @retry="exportFile"
        @cancel="exporting.cancel"
      />
    </section>
  </section>
</template>
