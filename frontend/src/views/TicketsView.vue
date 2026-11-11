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
import type { Page, WorkTaskItem, AgentSummary, WorkTaskBundle } from '../types/api.generated'
import RequestStatus from '../components/RequestStatus.vue'
import PageControls from '../components/PageControls.vue'
import EmptyState from '../components/EmptyState.vue'
import AttachmentGallery from '../components/AttachmentGallery.vue'
import TicketCopy from '../components/TicketCopy.vue'
import AdminTicketEditor from '../components/AdminTicketEditor.vue'
import AdminDeleteButton from '../components/AdminDeleteButton.vue'
const props = defineProps<{ management?: boolean }>()
const { t } = useI18n(), route = useRoute(), auth = useAuthStore(), notifications = useNotificationsStore()
const administrator = computed(() => auth.user?.role === 'admin')
const managementMode = computed(() => !!props.management && administrator.value)
const editingTicket = ref<WorkTaskItem | null>(null)
const supervisor = computed(() => ['admin', 'qc'].includes(auth.user?.role ?? ''))
const status = ref<'pending' | 'handled' | 'all'>(route.query.status === 'handled' ? 'handled' : route.query.status === 'pending' ? 'pending' : managementMode.value ? 'all' : 'pending'), day = ref(''), creator = ref(''),
  bookingKey = ref(String(route.query.booking_key ?? '')), page = ref(1), handling = ref<number | null>(null),
  handlingNote = ref<Record<number, string>>({}), agents = ref<AgentSummary[]>([])
const selected = ref<number[]>([]), detailId = ref<number | null>(null)
const detail = useRequest(async ({ signal, timeoutMs }, id: number) => (await api.get<WorkTaskItem>(`/work-tasks/${id}`, { signal, timeout: timeoutMs })).data, { timeoutMs: timeouts.list })
const merge = useRequest(async ({ signal, timeoutMs }, ids: number[]) => (await api.post<WorkTaskBundle>('/work-tasks/merge', { ids }, { signal, timeout: timeoutMs })).data, { timeoutMs: timeouts.task })
async function ticketSaved(item: WorkTaskItem) {
  editingTicket.value = null
  if (detailId.value === item.id) detail.data.value = item
  clearSelection()
  await load()
}
async function ticketDeleted(id: number) {
  if (detailId.value === id) closeDetail()
  if (editingTicket.value?.id === id) editingTicket.value = null
  clearSelection()
  await load()
  if (!request.data.value?.items.length && page.value > 1) { page.value--; await load() }
}
async function editTicket(id: number) {
  await openTicket(id)
  if (detail.state.value === 'success' && detail.data.value?.id === id) editingTicket.value = detail.data.value
}
async function openTicket(id: number) { detailId.value = id; await detail.run(id) }
async function combine() { if (selected.value.length >= 2) { merge.data.value = undefined; await merge.run([...selected.value]) } }
function clearSelection() { selected.value = []; merge.data.value = undefined; merge.cancel() }
function closeDetail() { detailId.value = null; detail.cancel(); detail.data.value = undefined }
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
async function load(reset = false) { if (reset) { page.value = 1; clearSelection() }; await request.run() }
async function changePage(value: number) { page.value = value; await load() }
async function markHandled(item: WorkTaskItem) {
  if (handling.value !== null) return
  handling.value = item.id
  try { const updated = await handle.run(item); if (updated) { if (detailId.value === item.id) detail.data.value = updated; await load() } } finally { handling.value = null }
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
  const requestedTicket = Number(route.query.ticket_id)
  if (Number.isSafeInteger(requestedTicket) && requestedTicket > 0) void openTicket(requestedTicket)
  if (supervisor.value) void api.get<AgentSummary[]>('/users/lookup', { params: { limit: 50 } }).then(r => { agents.value = r.data }).catch(() => undefined)
})
</script>
<template>
  <section class="page-shell tickets-view" :class="{ 'admin-tickets-view': managementMode }">
    <header class="page-heading summary-heading"><div><component :is="managementMode ? 'h2' : 'h1'">{{ t(managementMode ? 'ticketAdmin.title' : supervisor ? 'workTaskUi.qcTitle' : 'workTaskUi.myTitle') }}</component><p>{{ t(managementMode ? 'ticketAdmin.intro' : 'workTaskUi.intro') }}</p></div>
      <RouterLink v-if="administrator && !managementMode" class="button" :to="{ name: 'admin-tickets' }">{{ t('ticketAdmin.title') }}</RouterLink>
      <RouterLink v-if="managementMode" class="button" :to="{ name: 'admin-trash' }">{{ t('adminUi.trash') }}</RouterLink>
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
    <div v-if="supervisor && selected.length" class="ticket-merge-toolbar" role="region" :aria-label="t('ticketCompose.merge')">
      <span>{{ t('ticketCompose.selected', { count: selected.length }) }}</span>
      <button type="button" class="button primary" :disabled="selected.length < 2 || merge.pending.value" @click="combine">{{ t('ticketCompose.merge') }}</button>
      <button type="button" class="text-button" @click="clearSelection">{{ t('ticketCompose.clearSelection') }}</button>
    </div>
    <RequestStatus :state="merge.state.value" :error="merge.error.value" @retry="combine" />
    <section v-if="merge.data.value" class="ticket-detail ticket-bundle" :aria-label="t('ticketCompose.merged')">
      <h2>{{ t('ticketCompose.merged') }}</h2>
      <p class="input-hint">{{ t('ticketCompose.mergeHint') }}</p>
      <h3>{{ merge.data.value.title }}</h3><p class="ticket-message">{{ merge.data.value.message }}</p>
      <TicketCopy :title="merge.data.value.title" :message="merge.data.value.message" />
      <AttachmentGallery :files="merge.data.value.attachments" />
    </section>
    <section v-if="detailId !== null" class="ticket-detail" :aria-label="t('ticketCompose.detail')" aria-live="polite">
      <header class="ticket-actions"><h2>{{ t('ticketCompose.detail') }} #{{ detailId }}</h2><button type="button" class="text-button" @click="closeDetail">{{ t('ticketCompose.close') }}</button></header>
      <RequestStatus :state="detail.state.value" :error="detail.error.value" @retry="openTicket(detailId!)" />
      <template v-if="detail.data.value?.id === detailId">
        <h3>{{ detail.data.value.title }}</h3>
        <RouterLink class="table-booking-link" :to="{ name: 'booking', params: { key: detail.data.value.booking_key } }">{{ detail.data.value.display_key }}</RouterLink>
        <p>{{ detail.data.value.supplier_name }}</p>
        <p class="ticket-meta">{{ detail.data.value.creator.full_name }} · {{ formatDateTime(detail.data.value.created_at, auth.timezone) }} · {{ t(`workTaskUi.${detail.data.value.status}`) }}</p>
        <div v-if="managementMode" class="ticket-admin-actions ticket-actions"><button type="button" class="button" @click="editingTicket = detail.data.value">{{ t('ticketAdmin.edit') }}</button><AdminDeleteButton resource="tickets" :identifier="detail.data.value.id" :label="detail.data.value.title" @deleted="ticketDeleted(detailId!)" /></div>
        <p class="ticket-message">{{ detail.data.value.message }}</p>
        <TicketCopy :title="detail.data.value.title" :message="detail.data.value.message" />
        <h3>{{ t('ticketCompose.images') }}</h3>
        <AttachmentGallery v-if="detail.data.value.attachments?.length" :files="detail.data.value.attachments ?? []" />
        <p v-else class="muted">{{ t('ticketCompose.noImages') }}</p>
        <div v-if="detail.data.value.handled_by" class="ticket-handled"><strong>{{ t('workTaskUi.handledBy', { user: detail.data.value.handled_by.full_name }) }}</strong><time v-if="detail.data.value.handled_at">{{ formatDateTime(detail.data.value.handled_at, auth.timezone) }}</time><p v-if="detail.data.value.handling_note">{{ detail.data.value.handling_note }}</p></div>
        <form v-else-if="supervisor" class="ticket-handle-form" @submit.prevent="markHandled(detail.data.value)"><label :for="`handling-${detailId}`">{{ t('workTaskUi.handlingNote') }}</label><textarea :id="`handling-${detailId}`" v-model="handlingNote[detailId]" maxlength="2000" rows="2" :disabled="handling !== null" /><button class="button primary" type="submit" :disabled="handling !== null">{{ t('workTaskUi.markHandled') }}</button></form>
      </template>
    </section>
    <div class="ticket-list" v-if="request.data.value?.items.length">
      <article v-for="item in request.data.value.items" :key="item.id" class="ticket-card">
        <header><div><span class="ticket-number">#{{ item.id }}</span><RouterLink class="table-booking-link" :to="{ name: 'booking', params: { key: item.booking_key } }">{{ item.display_key }}</RouterLink></div><span class="ticket-status" :class="item.status">{{ t(`workTaskUi.${item.status}`) }}</span></header>
        <label v-if="supervisor && item.issue_type === 'cannot_send_rejection_letters'" class="ticket-select"><input v-model="selected" :value="item.id" type="checkbox" :disabled="!selected.includes(item.id) && selected.length >= 100" />{{ t('ticketCompose.selectMerge') }}</label>
        <h2 class="ticket-card-title"><button type="button" class="text-button" @click="openTicket(item.id)">{{ item.title }}</button></h2>
        <p class="ticket-supplier">{{ item.supplier_name }}</p><p class="ticket-message ticket-excerpt">{{ item.message }}</p>
        <p class="ticket-meta">{{ item.creator.full_name }} · {{ formatDateTime(item.created_at, auth.timezone) }} · {{ t('ticketCompose.imageCount', { count: item.attachments?.length ?? 0 }) }}</p>
        <div class="ticket-actions"><button type="button" class="button" @click="openTicket(item.id)">{{ t('ticketCompose.open') }}</button><template v-if="managementMode"><button type="button" class="button" @click="editTicket(item.id)">{{ t('ticketAdmin.edit') }}</button><AdminDeleteButton resource="tickets" :identifier="item.id" :label="item.title" @deleted="ticketDeleted(item.id)" /></template></div>
      </article>
    </div>
    <EmptyState v-else-if="request.state.value === 'success'" :title="t('workTaskUi.empty')" :description="t('workTaskUi.emptyHint')" />
    <AdminTicketEditor v-if="managementMode && editingTicket" :key="editingTicket.id" :ticket="editingTicket" @saved="ticketSaved" @close="editingTicket = null" />
    <PageControls summary-key="workTaskUi.pageOf" :page="page" :size="20" :total="request.data.value?.total ?? 0" @change="changePage" />
  </section>
</template>
