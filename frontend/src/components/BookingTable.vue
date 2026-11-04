<script setup lang="ts">
import { computed, toRef, onScopeDispose } from 'vue'
import { useVirtualList } from '@vueuse/core'
import { useBookingsStore } from '../stores/bookings'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { formatDateTime } from '../utils/dateTime'
import type { BookingItem } from '../types/api.generated'
import TaskButton from './TaskButton.vue'
import WatchButton from './WatchButton.vue'
import { ref } from 'vue'
import { useListNavigation } from '../composables/useListNavigation'
import { useCollaborationStore } from '../stores/collaboration'
import { useTasksStore } from '../stores/tasks'
import StatusTag from './StatusTag.vue'
import EmptyState from './EmptyState.vue'
const { t } = useI18n(),
  auth = useAuthStore()
const props = defineProps<{
  rows: BookingItem[]
  loading?: boolean
  page?: number
  total?: number
  size?: number
}>()
const emit = defineEmits<{ open: [key: string]; page: [number] }>()
const root = ref<HTMLElement | null>(null),
  collaboration = useCollaborationStore(),
  tasks = useTasksStore()
const nav = useListNavigation('booking-table', root, () => props.rows.map((r) => r.booking_key), {
  open: (i) => emit('open', props.rows[i]!.booking_key),
  watch: (i) => collaboration.toggle(props.rows[i]!.booking_key, props.rows[i]!.my_watching),
  task: (i) => tasks.openDialog(props.rows[i]!.booking_key),
  reveal: (i) => {
    if (props.rows.length > 50) scrollTo(i)
  },
  page: (delta) => {
    const p = (props.page ?? 1) + delta
    if (
      props.page !== undefined &&
      p >= 1 &&
      p <= Math.max(1, Math.ceil((props.total ?? 0) / (props.size ?? 20)))
    )
      emit('page', p)
  },
})
const { list, containerProps, scrollTo } = useVirtualList(toRef(props, 'rows'), {
  itemHeight: 100,
  overscan: 3,
})
const shown = computed(() => (props.rows.length > 50 ? list.value.map((v) => v.data) : props.rows))
const store = useBookingsStore()
const prefetch = useRequest((ctx, key: string) => store.lookup(ctx, key), {
  timeoutMs: timeouts.lookup,
})
let hoverTimer: ReturnType<typeof setTimeout> | undefined
function hover(key: string) {
  clearTimeout(hoverTimer)
  hoverTimer = setTimeout(() => {
    void import('../views/BookingDetailView.vue')
    void prefetch.run(key)
  }, 150)
}
function focused(row: BookingItem) {
  nav.selected(props.rows.indexOf(row))
  hover(row.booking_key)
}
function leave() {
  clearTimeout(hoverTimer)
}
onScopeDispose(leave)
const columns = [
  'booking',
  'supplier',
  'station',
  'type',
  'period',
  'status',
  'position',
  'agent',
  'latestNote',
  'updatedAt',
]
</script>
<template>
  <div
    ref="root"
    class="booking-table-wrap"
    :class="{ 'table-virtual': rows.length > 50 }"
    v-bind="rows.length > 50 ? containerProps : {}"
    :aria-busy="loading"
  >
    <div
      v-if="loading && !rows.length"
      class="skeleton-table"
      role="status"
      :aria-label="t('common.loading')"
    >
      <div v-for="n in 6" :key="n" class="skeleton-line" />
    </div>
    <table v-else-if="rows.length" class="booking-table">
      <caption class="sr-only">
        {{
          t('bookingUi.bookingsTable')
        }}
      </caption>
      <thead>
        <tr>
          <th v-for="column in columns" :key="column" scope="col">
            {{ t(`bookingUi.${column}`) }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-if="rows.length > 50 && list[0]?.index"
          aria-hidden="true"
          :style="{ height: `${list[0]!.index * 100}px` }"
        >
          <td :colspan="columns.length" style="padding: 0; border: 0" />
        </tr>
        <tr
          v-for="row in shown"
          :key="row.booking_key"
          :data-nav-key="row.booking_key"
          :tabindex="nav.tabindex(rows.indexOf(row))"
          @mouseenter="hover(row.booking_key)"
          @mouseleave="leave"
          @focusin="focused(row)"
          @focusout="leave"
          @click="$emit('open', row.booking_key)"
        >
          <td>
            <button
              type="button"
              class="table-booking-link"
              @click.stop="$emit('open', row.booking_key)"
            >
              {{ row.display_key }}</button
            ><TaskButton
              :booking-key="row.booking_key"
              :count="row.my_pending_tasks"
              compact
            /><WatchButton :booking-key="row.booking_key" :watching="row.my_watching" /><span
              v-if="row.is_stale"
              class="row-stale-label"
              >{{ t('bookingUi.stale') }}</span
            >
          </td>
          <td>{{ row.supplier.name }}</td>
          <td>{{ row.station_code }}</td>
          <td>{{ t(`supplier_types.${row.supplier.type}`) }}</td>
          <td>{{ row.period_label }}</td>
          <td><StatusTag :status="row.last_status" /></td>
          <td>{{ row.last_position || t('common.unknown') }}</td>
          <td>{{ row.last_agent?.full_name || t('common.unknown') }}</td>
          <td class="table-note">
            <span :title="row.last_note_preview || undefined">{{
              row.last_note_preview || t('bookingUi.noNote')
            }}</span>
          </td>
          <td>
            <time :datetime="row.updated_at">{{
              formatDateTime(row.updated_at, auth.timezone)
            }}</time>
          </td>
        </tr>
        <tr
          v-if="rows.length > 50"
          aria-hidden="true"
          :style="{
            height: `${Math.max(0, rows.length - (list.at(-1)?.index ?? -1) - 1) * 100}px`,
          }"
        >
          <td :colspan="columns.length" style="padding: 0; border: 0" />
        </tr>
      </tbody>
    </table>
    <EmptyState
      v-else
      :title="t('bookingUi.emptyBookings')"
      :description="t('bookingUi.emptyFilters')"
    />
    <slot name="footer" />
  </div>
</template>
