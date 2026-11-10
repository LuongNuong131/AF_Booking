<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useNotificationsStore } from '../stores/notifications'
import { useRequest } from '../composables/useRequest'
import { useViewRefresh } from '../composables/useViewRefresh'
import { timeouts } from '../config/timeouts'
import { formatDateTime } from '../utils/dateTime'
import { downloadReport, saveDownload } from '../utils/download'
import { normalizeBookingKey } from '../utils/bookingKey'
import type { Page, WorkTaskItem, AgentSummary } from '../types/api.generated'
import RequestStatus from '../components/RequestStatus.vue'
import PageControls from '../components/PageControls.vue'
import EmptyState from '../components/EmptyState.vue'
const { t } = useI18n(), route = useRoute(), auth = useAuthStore(), notifications = useNotificationsStore()
const supervisor = computed(() => ['admin', 'qc'].includes(auth.user?.role ?? ''))
const status = ref<'pending' | 'handled' | 'all'>(route.query.status === 'handled' ? 'handled' : 'pending'), day = ref(''), creator = ref(''),
  bookingKey = ref(String(route.query.booking_key ?? '')), page = ref(1), handling = ref<number | null>(null),
  handlingNote = ref<Record<number, string>>({}), agents = ref<AgentSummary[]>([])
const params = computed(() => ({ status: status.value, date: day.value || undefined,
  creator_id: supervisor.value && creator.value ? Number(creator.value) : undefined,
  booking_key: bookingKey.value.trim() ? normalizeBookingKey(bookingKey.value) : undefined }))
const request = useRequest(async ({ signal, timeoutMs }) => (await api.get<Page<WorkTaskItem>>('/work-tasks', {
  params: { ...params.value, page: page.value, size: 20 }, signal, timeout: timeoutMs,
})).data, { timeoutMs: timeouts.list, retry: true })
const handle = useRequest(async ({ signal, timeoutMs }, item: WorkTaskItem) => (await api.post<WorkTaskItem>(`/work-tasks/${item.id}/handle`, {
  handling_note: handlingNote.value[item.id]?.trim() || null,
}, { signal, timeout: timeoutMs })).data, { timeoutMs: timeouts.task })
const exporting = useRequest(ctx => downloadReport(ctx, '/work-tasks/export', Object.fromEntries(Object.entries(params.value).filter(([, value]) => value !== undefined).map(([key, value]) => [key, String(value)]))), { timeoutMs: timeouts.export })
async function load(reset = false) { if (reset) page.value = 1; await request.run() }
async function changePage(value: number) { page.value = value; await load() }
async function markHandled(item: WorkTaskItem) {
  if (handling.value !== null) return
  handling.value = item.id
  try { if (await handle.run(item)) await load() } finally { handling.value = null }
}
async function download() { const value = await exporting.run(); if (value) saveDownload(value, 'qc-tickets.xlsx') }
watch(() => notifications.unread, () => void load())
watch(() => [route.query.booking_key, route.query.status], () => {
  bookingKey.value = String(route.query.booking_key ?? '')
  if (route.query.status === 'pending' || route.query.status === 'handled') status.value = route.query.status
  void load(true)
})
useViewRefresh(() => load())
onMounted(() => {
  void load()
  if (supervisor.value) void api.get<AgentSummary[]>('/users/lookup', { params: { limit: 50 } }).then(r => { agents.value = r.data }).catch(() => undefined)
})
</script>
<template>
  <section class="page-shell tickets-view">
    <header class="page-heading summary-heading"><div><h1>{{ t(supervisor ? 'workTaskUi.qcTitle' : 'workTaskUi.myTitle') }}</h1><p>{{ t('workTaskUi.intro') }}</p></div>
      <button v-if="supervisor" class="button primary" :disabled="exporting.pending.value" @click="download">{{ t('opsUi.downloadExcel') }}</button>
    </header>
    <form class="workflow-controls ticket-filters" @submit.prevent="load(true)">
      <label>{{ t('workTaskUi.status') }}<select v-model="status" :aria-label="t('workTaskUi.status')"><option value="pending">{{ t('workTaskUi.pending') }}</option><option value="handled">{{ t('workTaskUi.handled') }}</option><option value="all">{{ t('workTaskUi.all') }}</option></select></label>
      <label>{{ t('workTaskUi.createdDate') }}<input v-model="day" type="date" /></label>
      <label v-if="supervisor">{{ t('workTaskUi.creator') }}<select v-model="creator"><option value="">{{ t('bookingUi.allAgents') }}</option><option v-for="agent in agents" :key="agent.id" :value="String(agent.id)">{{ agent.full_name }}</option></select></label>
      <label>{{ t('bookingUi.booking') }}<input v-model="bookingKey" maxlength="40" placeholder="CW 1234567-YUL-2611" /></label>
      <button class="button" type="submit" :disabled="request.pending.value">{{ t('adminUi.apply') }}</button>
    </form>
    <p class="report-explanation">{{ t('workTaskUi.pendingHint') }}</p>
    <RequestStatus :state="request.state.value" :error="request.error.value" @retry="load()" />
    <RequestStatus :state="handle.state.value" :error="handle.error.value" />
    <RequestStatus :state="exporting.state.value" :error="exporting.error.value" @retry="download" />
    <div class="ticket-list" v-if="request.data.value?.items.length">
      <article v-for="item in request.data.value.items" :key="item.id" class="ticket-card">
        <header><div><span class="ticket-number">#{{ item.id }}</span><RouterLink class="table-booking-link" :to="{ name: 'booking', params: { key: item.booking_key } }">{{ item.display_key }}</RouterLink></div><span class="ticket-status" :class="item.status">{{ t(`workTaskUi.${item.status}`) }}</span></header>
        <p class="ticket-supplier">{{ item.supplier_name }}</p><p class="ticket-message">{{ item.message }}</p>
        <p class="ticket-meta">{{ item.creator.full_name }} · {{ formatDateTime(item.created_at, auth.timezone) }}</p>
        <div v-if="item.handled_by" class="ticket-handled"><strong>{{ t('workTaskUi.handledBy', { user: item.handled_by.full_name }) }}</strong><time v-if="item.handled_at">{{ formatDateTime(item.handled_at, auth.timezone) }}</time><p v-if="item.handling_note">{{ item.handling_note }}</p></div>
        <form v-else-if="supervisor" class="ticket-handle-form" @submit.prevent="markHandled(item)"><label :for="`handling-${item.id}`">{{ t('workTaskUi.handlingNote') }}</label><textarea :id="`handling-${item.id}`" v-model="handlingNote[item.id]" maxlength="2000" rows="2" :disabled="handling !== null" /><button class="button primary" type="submit" :disabled="handling !== null">{{ t('workTaskUi.markHandled') }}</button></form>
      </article>
    </div>
    <EmptyState v-else-if="request.state.value === 'success'" :title="t('workTaskUi.empty')" :description="t('workTaskUi.emptyHint')" />
    <PageControls summary-key="workTaskUi.pageOf" :page="page" :size="20" :total="request.data.value?.total ?? 0" @change="changePage" />
  </section>
</template>
