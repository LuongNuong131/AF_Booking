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
import StatusTag from './StatusTag.vue'
import EmptyState from './EmptyState.vue'
const { t } = useI18n(),
  auth = useAuthStore()
const props = defineProps<{ rows: BookingItem[]; loading?: boolean }>()
defineEmits<{ open: [key: string] }>()
const { list, containerProps } = useVirtualList(toRef(props, 'rows'), {
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
          v-memo="[row, auth.timezone]"
          @mouseenter="hover(row.booking_key)"
          @mouseleave="leave"
          @focusin="hover(row.booking_key)"
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
            /><span v-if="row.is_stale" class="row-stale-label">{{ t('bookingUi.stale') }}</span>
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
