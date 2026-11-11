<script setup lang="ts">
import { computed, ref, shallowRef, watch, onScopeDispose } from 'vue'
import { ElDialog } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../../stores/auth'
import { usePagedApi } from '../../composables/usePagedApi'
import { useRequest } from '../../composables/useRequest'
import { api } from '../../api/client'
import { timeouts } from '../../config/timeouts'
import { formatDateTime } from '../../utils/dateTime'
import type { IntegrityRunDTO, JsonValue, IntegrityHistory } from '../../types/api.generated'
import RequestStatus from '../../components/RequestStatus.vue'
import PageControls from '../../components/PageControls.vue'
const { t } = useI18n(),
  auth = useAuthStore()
const list = usePagedApi<IntegrityRunDTO>(() => '/admin/integrity')
const config = computed(() => list.request.data.value as IntegrityHistory | undefined)
const fixing = shallowRef<IntegrityRunDTO | null>(null),
  selected = shallowRef<IntegrityRunDTO | null>(null),
  findingPage = ref(1)
const running = computed(() => list.items.value.some((row) => row.status === 'running'))
const mutation = useRequest(
  async ({ signal, timeoutMs }, mode: 'run' | 'fix', id?: number) =>
    (
      await api.post<IntegrityRunDTO>(
        `/admin/integrity/${mode}`,
        mode === 'fix' ? { run_id: id } : undefined,
        { signal, timeout: timeoutMs },
      )
    ).data,
  { timeoutMs: timeouts.list },
)
async function run(mode: 'run' | 'fix' = 'run', id?: number) {
  if (mutation.pending.value || running.value) return
  if (await mutation.run(mode, id)) {
    fixing.value = null
    list.page.value = 1
    await list.load()
  }
}
function view(row: IntegrityRunDTO) {
  selected.value = row
  findingPage.value = 1
}
const findings = computed(
  () =>
    selected.value?.details.items?.slice((findingPage.value - 1) * 20, findingPage.value * 20) ??
    [],
)
const value = (v: JsonValue) => (v === null ? '—' : typeof v === 'string' ? v : JSON.stringify(v))
watch(list.items, (rows) => {
  if (selected.value) {
    const row = rows.find((r) => r.id === selected.value!.id)
    if (row) selected.value = row
  }
})
// Only this Admin progress view polls, and only while a run is active and reads succeed.
const timer = setInterval(() => {
  if (running.value && !list.request.pending.value && list.request.state.value === 'success')
    void list.load()
}, 2000)
onScopeDispose(() => clearInterval(timer))
</script>
<template>
  <section class="admin-panel">
    <header class="admin-section-heading">
      <div>
        <h2>{{ t('guardUi.integrityTitle') }}</h2>
        <p class="muted">{{ t('guardUi.integrityDescription') }}</p>
      </div>
      <button
        type="button"
        class="button primary"
        :disabled="running || mutation.pending.value"
        @click="run()"
      >
        {{ t('guardUi.run') }}
      </button>
    </header>
    <aside class="integrity-explainer"><h3>{{ t('integrityHelp.title') }}</h3><p>{{ t('integrityHelp.description') }}</p><div><article><strong>1 · {{ t('integrityHelp.scan') }}</strong><p>{{ t('integrityHelp.scanHint') }}</p></article><article><strong>2 · {{ t('integrityHelp.review') }}</strong><p>{{ t('integrityHelp.reviewHint') }}</p></article><article><strong>3 · {{ t('integrityHelp.repair') }}</strong><p>{{ t('integrityHelp.repairHint') }}</p></article></div><p class="muted">{{ t('integrityHelp.example') }}</p></aside>
    <button
      type="button"
      class="text-button"
      :disabled="list.request.pending.value"
      @click="list.load"
    >
      {{ t('guardUi.refresh') }}
    </button>
    <p v-if="config?.autofix_enabled" class="booking-warning">{{ t('guardUi.autofixEnabled') }}</p>
    <p v-if="config" class="muted">
      {{ t('guardUi.schedule', { time: config.run_time, zone: config.timezone }) }}
    </p>
    <RequestStatus :state="mutation.state.value" :error="mutation.error.value" />
    <RequestStatus
      :state="list.request.state.value"
      :error="list.request.error.value"
      @retry="list.load"
    />
    <div v-if="list.request.pending.value && !list.items.value.length" class="booking-skeleton">
      <div v-for="n in 3" :key="n" class="skeleton-line" />
    </div>
    <p v-else-if="!list.items.value.length" class="muted">{{ t('guardUi.noRuns') }}</p>
    <article
      v-for="row in list.items.value"
      :key="row.id"
      class="integrity-history-card admin-panel"
    >
      <header>
        <strong>#{{ row.id }} · {{ t(`guardUi.${row.status}`) }}</strong
        ><span
          >{{ t(row.details.mode === 'fix' ? 'guardUi.repair' : 'guardUi.report') }} ·
          {{ t(`guardUi.${row.details.trigger}`) }}</span
        >
      </header>
      <small
        >{{ t('guardUi.started') }}: {{ formatDateTime(row.started_at, auth.timezone) }}<br />{{
          t('guardUi.finished')
        }}: {{ row.finished_at ? formatDateTime(row.finished_at, auth.timezone) : '—' }}</small
      >
      <div class="integrity-counts">
        <span>{{ t('guardUi.checked') }}: {{ row.checked }}</span
        ><span>{{ t('guardUi.mismatched') }}: {{ row.mismatched }}</span
        ><span>{{ t('guardUi.fixed') }}: {{ row.fixed }}</span>
      </div>
      <p v-if="row.details.error" class="field-error">{{ row.details.error }}</p>
      <div class="admin-form-actions">
        <button
          type="button"
          class="button"
          :disabled="!row.details.items?.length"
          @click="view(row)"
        >
          {{ t('guardUi.findings') }}</button
        ><button
          type="button"
          class="button"
          :disabled="running || mutation.pending.value || !row.mismatched"
          @click="fixing = row"
        >
          {{ t('guardUi.fix') }}
        </button>
      </div>
    </article>
    <PageControls
      :page="list.page.value"
      :size="20"
      :total="list.total.value"
      summary-key="guardUi.runPageOf"
      @change="list.page.value = $event"
    />
    <ElDialog
      :model-value="!!selected"
      :title="t('guardUi.findings')"
      width="980px"
      @update:model-value="selected = null"
    >
      <p v-if="selected?.details.truncated" class="booking-warning">{{ t('guardUi.truncated') }}</p>
      <article v-for="finding in findings" :key="finding.booking_key" class="integrity-finding">
        <RouterLink :to="{ name: 'booking', params: { key: finding.booking_key } }">{{
          finding.display_key
        }}</RouterLink
        ><span v-if="finding.fixed"> · {{ t('guardUi.fixed') }}</span>
        <p v-if="!finding.repairable" class="field-error">{{ t('guardUi.unrepairable') }}</p>
        <table class="integrity-differences">
          <thead>
            <tr>
              <th>{{ t('guardUi.field') }}</th>
              <th>{{ t('guardUi.actual') }}</th>
              <th>{{ t('guardUi.expected') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(diff, name) in finding.fields" :key="name">
              <td>{{ name }}</td>
              <td>{{ value(diff.actual) }}</td>
              <td>{{ value(diff.expected) }}</td>
            </tr>
          </tbody>
        </table>
      </article>
      <PageControls
        :page="findingPage"
        :total="selected?.details.items?.length ?? 0"
        :size="20"
        @change="findingPage = $event"
      />
    </ElDialog>
    <ElDialog
      :model-value="!!fixing"
      :title="t('guardUi.fixTitle')"
      width="600px"
      :close-on-click-modal="false"
      :close-on-press-escape="!mutation.pending.value"
      :show-close="!mutation.pending.value"
      @update:model-value="fixing = null"
    >
      <p>{{ t('guardUi.fixBody') }}</p>
      <RequestStatus :state="mutation.state.value" :error="mutation.error.value" />
      <template #footer
        ><button
          type="button"
          class="button"
          :disabled="mutation.pending.value"
          @click="fixing = null"
        >
          {{ t('guardUi.cancel') }}</button
        ><button
          type="button"
          class="button primary"
          :disabled="mutation.pending.value"
          @click="run('fix', fixing!.id)"
        >
          {{ t('guardUi.confirmFix') }}
        </button></template
      >
    </ElDialog>
  </section>
</template>
