<script setup lang="ts">
import { ref, watch, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { timeouts } from '../config/timeouts'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { useBookingRows, patchBooking } from '../composables/useBookingRows'
import { useBookingsStore } from '../stores/bookings'
import { useViewRefresh } from '../composables/useViewRefresh'
import { useListNavigation } from '../composables/useListNavigation'
import { useCollaborationStore } from '../stores/collaboration'
import { useTasksStore } from '../stores/tasks'
import { useAuthStore } from '../stores/auth'
import { formatDateTime } from '../utils/dateTime'
import type { Page, AssignmentItem, BookingItem } from '../types/api.generated'
import BookingTable from './BookingTable.vue'
import FollowedFolders from './FollowedFolders.vue'
import PageControls from './PageControls.vue'
import RequestStatus from './RequestStatus.vue'
import { ElDialog } from 'element-plus'
const props = defineProps<{ mode: 'assignments' | 'watching' }>(),
  { t } = useI18n(),
  store = useCollaborationStore(),
  tasks = useTasksStore(),
  auth = useAuthStore()
const followView = ref<'bookings' | 'folders'>('folders')
const page = ref(1),
  view = ref<'to_me' | 'from_me'>('to_me'),
  status = ref<'open' | 'done' | 'declined'>('open'),
  root = ref<HTMLElement | null>(null)
const request = useRequest(
  async ({ signal, timeoutMs }) =>
    (
      await api.get<Page<AssignmentItem | BookingItem>>(
        props.mode === 'watching' ? '/watching' : '/assignments',
        {
          params: {
            page: page.value,
            size: 10,
            view: view.value,
            status: status.value,
          },
          signal,
          timeout: timeoutMs,
        },
      )
    ).data,
  { timeoutMs: timeouts.list, retry: true },
)
const assignments = computed(() =>
    props.mode === 'assignments' ? ((request.data.value?.items ?? []) as AssignmentItem[]) : [],
  ),
  bookings = computed(() =>
    props.mode === 'watching' ? ((request.data.value?.items ?? []) as BookingItem[]) : [],
  )
const catalog = useBookingsStore()
useBookingRows(
  (event) => {
    if (props.mode !== 'watching' || !request.data.value) return false
    const rows = request.data.value.items as BookingItem[]
    if (!rows.some((r) => r.booking_key === event.booking_key)) return false
    request.data.value = {
      ...request.data.value,
      items: rows.map((row) =>
        row.booking_key === event.booking_key ? patchBooking(row, event, catalog.statuses) : row,
      ),
    }
    return false
  },
  () => {},
)
const decline = ref<AssignmentItem | null>(null),
  reason = ref('')
const mutation = useRequest(
  async ({ signal, timeoutMs }, item: AssignmentItem, declineReason?: string) =>
    (
      await api.post<AssignmentItem>(
        `/assignments/${item.id}/${declineReason === undefined ? 'complete' : 'decline'}`,
        declineReason === undefined ? undefined : { reason: declineReason },
        { signal, timeout: timeoutMs },
      )
    ).data,
  { timeoutMs: timeouts.task },
)
async function load() {
  if (props.mode === 'watching' && followView.value === 'folders') return
  await request.run()
}
function changePage(delta: number) {
  const next = page.value + delta
  if (next >= 1 && next <= Math.max(1, Math.ceil((request.data.value?.total ?? 0) / 10)))
    page.value = next
}
const nav = useListNavigation('assignments', root, () => assignments.value.map((r) => r.id), {
  open: (i) => tasks.openBooking(assignments.value[i]!.booking_key),
  watch: (i) => store.toggle(assignments.value[i]!.booking_key),
  task: (i) => tasks.openDialog(assignments.value[i]!.booking_key),
  page: changePage,
})
async function resolve(item: AssignmentItem, declineReason?: string) {
  if (mutation.pending.value) return
  const result = await mutation.run(item, declineReason)
  if (result) {
    decline.value = null
    store.changed()
    await load()
  }
}
function askDecline(item: AssignmentItem) {
  decline.value = item
  reason.value = ''
}
watch([() => props.mode, view, status], () => {
  page.value = 1
  void load()
})
watch(followView, () => { page.value = 1; void load() })
watch(page, load)
watch(
  () => store.revision,
  () => void load(),
)
useViewRefresh(load)
onMounted(load)
</script>
<template>
  <section
    ref="root"
    class="collaboration-list"
    :aria-label="t(mode === 'assignments' ? 'collabUi.assignments' : 'collabUi.watching')"
  >
    <div v-if="mode === 'assignments'" class="task-list-toolbar">
      <label
        >{{ t('collabUi.direction')
        }}<select v-model="view" :aria-label="t('collabUi.direction')">
          <option value="to_me">{{ t('collabUi.toMe') }}</option>
          <option value="from_me">{{ t('collabUi.fromMe') }}</option>
        </select></label
      ><label
        >{{ t('collabUi.status')
        }}<select v-model="status" :aria-label="t('collabUi.status')">
          <option v-for="state in ['open', 'done', 'declined']" :key="state" :value="state">
            {{ t(`collabUi.${state}`) }}
          </option>
        </select></label
      >
    </div>
    <div v-if="mode === 'watching'" class="task-list-toolbar follow-view-tabs">
      <button v-for="tab in ['folders', 'bookings'] as const" :key="tab" type="button" class="button"
        :aria-pressed="followView === tab" @click="followView = tab">{{ t(`followUi.${tab}`) }}</button>
    </div>
    <FollowedFolders v-if="mode === 'watching' && followView === 'folders'" />
    <template v-else>
    <RequestStatus
      :state="request.state.value"
      :error="request.error.value"
      @retry="load"
    /><RequestStatus :state="mutation.state.value" :error="mutation.error.value" />
    <div v-if="request.pending.value && !request.data.value" class="skeleton-table">
      <div v-for="n in 3" :key="n" class="skeleton-line" />
    </div>
    <template v-else-if="mode === 'assignments'"
      ><article
        v-for="(row, i) in assignments"
        :key="row.id"
        class="task-row assignment-row"
        :data-nav-key="row.id"
        :tabindex="nav.tabindex(i)"
        @focusin="nav.selected(i)"
      >
        <button
          type="button"
          class="table-booking-link"
          @click="tasks.openBooking(row.booking_key)"
        >
          {{ row.display_key }}
        </button>
        <p>
          {{
            t('collabUi.fromTo', {
              from: row.from_user.full_name,
              to: row.to_user.full_name,
            })
          }}
        </p>
        <p v-if="row.message" class="task-message">{{ row.message }}</p>
        <small
          >{{ formatDateTime(row.created_at, auth.timezone) }} ·
          {{ t(`collabUi.${row.status}`) }}</small
        >
        <p v-if="row.decline_reason">{{ row.decline_reason }}</p>
        <div
          v-if="row.status === 'open' && row.to_user.id === auth.user?.id"
          class="admin-form-actions"
        >
          <button
            type="button"
            class="button"
            :disabled="mutation.pending.value"
            @click="resolve(row)"
          >
            {{ t('collabUi.complete') }}</button
          ><button
            type="button"
            class="button"
            :disabled="mutation.pending.value"
            @click="askDecline(row)"
          >
            {{ t('collabUi.decline') }}
          </button>
        </div>
      </article>
      <p v-if="!assignments.length" class="muted">
        {{ t('collabUi.emptyAssignments') }}
      </p></template
    ><BookingTable
      v-else
      :rows="bookings"
      :page="page"
      :total="request.data.value?.total ?? 0"
      :size="10"
      @page="page = $event"
      @open="tasks.openBooking"
    /><PageControls
      :page="page"
      :size="10"
      :summary-key="mode==='assignments'?'collabUi.assignmentPage':'bookingUi.pageOf'"
      :total="request.data.value?.total ?? 0"
      @change="page = $event"
    /><ElDialog
      :model-value="!!decline"
      :title="t('collabUi.declineTitle')"
      width="480px"
      :close-on-click-modal="false"
      @update:model-value="decline = null"
      ><form @submit.prevent="resolve(decline!, reason.trim())">
        <label
          >{{ t('collabUi.reason')
          }}<textarea v-model="reason" required maxlength="255" rows="3" /></label
        ><RequestStatus :state="mutation.state.value" :error="mutation.error.value" /><button
          type="submit"
          class="button primary"
          :disabled="!reason.trim() || mutation.pending.value"
        >
          {{ t('collabUi.decline') }}
        </button>
      </form></ElDialog
    >
    </template>
  </section>
</template>
