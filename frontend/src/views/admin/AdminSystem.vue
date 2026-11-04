<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../../api/client'
import { useRequest } from '../../composables/useRequest'
import { useVisibleInterval } from '../../composables/useVisibleInterval'
import { useSystemHealthStore } from '../../stores/systemHealth'
import { useAuthStore } from '../../stores/auth'
import { formatDateTime } from '../../utils/dateTime'
import { timeouts } from '../../config/timeouts'
import type { SystemHealth } from '../../types/api.generated'
import RequestStatus from '../../components/RequestStatus.vue'
const { t } = useI18n(),
  store = useSystemHealthStore(),
  auth = useAuthStore()
const request = useRequest(
  async ({ signal, timeoutMs }) =>
    (await api.get<SystemHealth>('/admin/system/health', { signal, timeout: timeoutMs })).data,
  { timeoutMs: timeouts.list },
)
async function load() {
  if (request.pending.value) return
  const result = await request.run()
  if (result) store.degraded = result.degraded
}
useVisibleInterval(load, 15000, request.cancel)
const health = computed(() => request.data.value)
const spark = computed(() => {
  const values = health.value?.points.map((p) => p.p95_ms ?? 0) ?? [],
    max = Math.max(500, ...values)
  return values
    .map((v, i) => `${(i * 600) / Math.max(1, values.length - 1)},${100 - (v / max) * 90}`)
    .join(' ')
})
</script>
<template>
  <section class="admin-panel system-health">
    <header class="admin-section-heading">
      <div>
        <h2>{{ t('opsUi.systemTitle') }}</h2>
        <p class="muted">{{ t('opsUi.memoryOnly') }}</p>
      </div>
      <button type="button" class="button" :disabled="request.pending.value" @click="load">
        {{ t('bookingUi.refresh') }}
      </button>
    </header>
    <RequestStatus
      :state="request.state.value"
      :error="request.error.value"
      @retry="load"
    /><template v-if="health"
      ><p v-if="health.degraded" class="booking-warning">{{ t('opsUi.degraded') }}</p>
      <div class="report-metrics">
        <article>
          <span>{{ t('opsUi.requests') }}</span
          ><strong>{{ health.total.requests }}</strong>
        </article>
        <article>
          <span>{{ t('opsUi.errorRate') }}</span
          ><strong>{{ (health.total.error_rate * 100).toFixed(1) }}%</strong>
        </article>
        <article>
          <span>p95 · ms</span><strong>{{ health.total.p95_ms ?? '—' }}</strong>
        </article>
        <article>
          <span>{{ t('opsUi.dbLatency') }}</span
          ><strong>{{ health.db_latency_ms?.toFixed(1) ?? '—' }}</strong>
        </article>
      </div>
      <p>
        {{
          t('opsUi.runtime', {
            version: health.version,
            uptime: Math.floor(health.uptime_seconds),
            sockets: health.websocket_connections,
            locks: health.soft_locks,
          })
        }}
      </p>
      <p>
        {{
          t('opsUi.pool', {
            size: health.pool.size,
            used: health.pool.checked_out,
            overflow: health.pool.overflow,
          })
        }}
      </p>
      <svg
        class="health-sparkline"
        viewBox="0 0 600 110"
        role="img"
        :aria-label="t('opsUi.sparkline')"
      >
        <polyline fill="none" stroke="currentColor" stroke-width="2" :points="spark" />
      </svg>
      <p class="muted">{{ t('opsUi.histogramHint') }}</p>
      <div class="booking-table-wrap">
        <table class="booking-table">
          <thead>
            <tr>
              <th>{{ t('opsUi.endpointGroup') }}</th>
              <th>{{ t('opsUi.requests') }}</th>
              <th>{{ t('opsUi.errorRate') }}</th>
              <th>p50</th>
              <th>p95</th>
              <th>p99</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in health.groups" :key="row.group">
              <td>{{ row.group }}</td>
              <td>{{ row.requests }}</td>
              <td>{{ (row.error_rate * 100).toFixed(1) }}%</td>
              <td>{{ row.p50_ms ?? '—' }}</td>
              <td>{{ row.p95_ms ?? '—' }}</td>
              <td>{{ row.p99_ms ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <h3>{{ t('opsUi.jobs') }}</h3>
      <div class="booking-table-wrap">
        <table class="booking-table">
          <thead>
            <tr>
              <th>{{ t('opsUi.job') }}</th>
              <th>{{ t('opsUi.lastRun') }}</th>
              <th>{{ t('opsUi.duration') }}</th>
              <th>{{ t('opsUi.lastError') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in health.jobs" :key="job.name">
              <td>
                {{ job.name }} <span v-if="job.running">· {{ t('opsUi.running') }}</span>
              </td>
              <td>
                {{ job.last_started_at ? formatDateTime(job.last_started_at, auth.timezone) : '—' }}
              </td>
              <td>{{ job.duration_ms?.toFixed(1) ?? '—' }}</td>
              <td>{{ job.last_error ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <h3>{{ t('opsUi.slowQueries') }}</h3>
      <p class="muted">{{ t('opsUi.fingerprintOnly') }}</p>
      <div class="booking-table-wrap">
        <table class="booking-table">
          <thead>
            <tr>
              <th>{{ t('opsUi.fingerprint') }}</th>
              <th>{{ t('opsUi.duration') }}</th>
              <th>{{ t('opsUi.observed') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in health.slow_queries" :key="i">
              <td>
                <code>{{ row.fingerprint.slice(0, 24) }}</code>
              </td>
              <td>{{ row.duration_ms.toFixed(1) }}</td>
              <td>{{ formatDateTime(row.at, auth.timezone) }}</td>
            </tr>
          </tbody>
        </table>
      </div></template
    >
  </section>
</template>
