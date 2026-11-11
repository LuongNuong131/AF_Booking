<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useNotificationsStore } from '../stores/notifications'
import { useRequest } from '../composables/useRequest'
import { useViewRefresh } from '../composables/useViewRefresh'
import { timeouts } from '../config/timeouts'
import { formatDateTime } from '../utils/dateTime'
import type { Page, WorkTaskItem } from '../types/api.generated'
import BaseIcon from './BaseIcon.vue'
import PageControls from './PageControls.vue'
import RequestStatus from './RequestStatus.vue'
const props = defineProps<{ bookingKey: string }>()
const emit = defineEmits<{ create: [] }>()
const { t } = useI18n(), auth = useAuthStore(), notifications = useNotificationsStore()
const active = ref<'pending' | 'handled'>('pending'), size = 5
let chooseInitial = true
function ticketList(status: 'pending' | 'handled') {
  const page = ref(1)
  const request = useRequest(async ({ signal, timeoutMs }) => (await api.get<Page<WorkTaskItem>>('/work-tasks', {
    params: { booking_key: props.bookingKey, status, page: page.value, size }, signal, timeout: timeoutMs,
  })).data, { timeoutMs: timeouts.list })
  async function load() {
    const result = await request.run()
    if (result && page.value > Math.max(1, Math.ceil(result.total / size))) {
      page.value = Math.max(1, Math.ceil(result.total / size)); await request.run()
    }
  }
  return { page, request, load }
}
const pending = ticketList('pending'), handled = ticketList('handled')
const current = computed(() => active.value === 'pending' ? pending : handled)
const items = computed(() => current.value.request.data.value?.items ?? [])
const refreshing = computed(() => pending.request.pending.value || handled.request.pending.value)
const supervisor = computed(() => ['admin', 'qc'].includes(auth.user?.role ?? ''))
async function refresh() {
  await Promise.all([pending.load(), handled.load()])
  if (chooseInitial && pending.request.state.value === 'success' && handled.request.state.value === 'success') {
    if (pending.request.data.value?.total === 0 && (handled.request.data.value?.total ?? 0) > 0) active.value = 'handled'
    chooseInitial = false
  }
}
async function changePage(page: number) {
  if (current.value.request.pending.value) return
  current.value.page.value = page; await current.value.load()
}
watch(() => props.bookingKey, () => {
  pending.request.cancel(); handled.request.cancel()
  pending.request.data.value = undefined; handled.request.data.value = undefined
  pending.page.value = handled.page.value = 1; chooseInitial = true; active.value = 'pending'
  void refresh()
})
watch(() => notifications.unread, () => void refresh())
useViewRefresh(refresh)
onMounted(() => void refresh())
async function showCreated() {
  active.value = 'pending'; pending.page.value = 1
  await refresh()
}
defineExpose({ refresh, showCreated })
</script>
<template>
  <section class="booking-ticket-history" :aria-labelledby="`booking-tickets-${bookingKey}`">
    <header class="booking-ticket-history-heading">
      <div><span class="booking-ticket-history-icon"><BaseIcon name="inbox" /></span><h3 :id="`booking-tickets-${bookingKey}`">{{ t('bookingTicketHistory.title') }}</h3></div>
      <button type="button" class="text-button" :disabled="refreshing" @click="refresh">{{ t('bookingTicketHistory.refresh') }}</button>
    </header>
    <p class="booking-ticket-history-hint">{{ t(supervisor ? 'bookingTicketHistory.teamHint' : 'bookingTicketHistory.mineHint') }}</p>
    <div class="booking-ticket-tabs" role="group" :aria-label="t('bookingTicketHistory.title')">
      <button type="button" :class="{ selected: active === 'pending' }" :aria-pressed="active === 'pending'" @click="active = 'pending'"><span class="ticket-state-dot pending" />{{ t('workTaskUi.pending') }}<span class="booking-ticket-count">{{ pending.request.data.value?.total ?? '…' }}</span></button>
      <button type="button" :class="{ selected: active === 'handled' }" :aria-pressed="active === 'handled'" @click="active = 'handled'"><span class="ticket-state-dot handled" />{{ t('workTaskUi.handled') }}<span class="booking-ticket-count">{{ handled.request.data.value?.total ?? '…' }}</span></button>
    </div>
    <RequestStatus :state="current.request.state.value" :error="current.request.error.value" @retry="current.load" />
    <ul v-if="items.length" class="booking-ticket-records" :aria-busy="current.request.pending.value">
      <li v-for="item in items" :key="item.id" class="booking-ticket-record">
        <div class="booking-ticket-record-top"><span class="ticket-number">#{{ item.id }}</span><span class="ticket-status" :class="item.status">{{ t(`workTaskUi.${item.status}`) }}</span></div>
        <RouterLink class="booking-ticket-history-title" :to="{ name: 'tickets', query: { booking_key: bookingKey, status: item.status, ticket_id: item.id } }">{{ item.title }}<BaseIcon name="arrow" /></RouterLink>
        <p class="booking-ticket-record-excerpt">{{ item.message }}</p>
        <p class="booking-ticket-record-meta">{{ item.creator.full_name }}<span aria-hidden="true">·</span><time :datetime="item.created_at">{{ formatDateTime(item.created_at, auth.timezone) }}</time><span v-if="item.attachments?.length">· {{ t('ticketCompose.imageCount', { count: item.attachments.length }) }}</span></p>
        <div v-if="item.handled_by" class="booking-ticket-record-outcome"><BaseIcon name="check" /><div><strong>{{ t('workTaskUi.handledBy', { user: item.handled_by.full_name }) }}</strong><time v-if="item.handled_at" :datetime="item.handled_at">{{ formatDateTime(item.handled_at, auth.timezone) }}</time><p v-if="item.handling_note">{{ item.handling_note }}</p></div></div>
      </li>
    </ul>
    <p v-else-if="current.request.state.value === 'success'" class="booking-ticket-history-empty"><BaseIcon :name="active === 'handled' ? 'check' : 'inbox'" />{{ t(active === 'handled' ? 'bookingTicketHistory.emptyHandled' : 'bookingTicketHistory.emptyPending') }}</p>
    <PageControls v-if="(current.request.data.value?.total ?? 0) > size" summary-key="workTaskUi.pageOf" :page="current.page.value" :size="size" :total="current.request.data.value?.total ?? 0" @change="changePage" />
    <footer class="booking-ticket-history-footer"><RouterLink class="text-button" :to="{ name: 'tickets', query: { booking_key: bookingKey, status: active } }">{{ t('workTaskUi.viewTickets') }}</RouterLink><button type="button" class="button" @click="emit('create')"><BaseIcon name="plus" />{{ t('workTaskUi.create') }}</button></footer>
  </section>
</template>
