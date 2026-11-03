<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { formatDateTime } from '../utils/dateTime'
import type { BookingItem } from '../types/api.generated'
import StatusTag from './StatusTag.vue'
import EmptyState from './EmptyState.vue'
const { t } = useI18n(),
  auth = useAuthStore()
defineProps<{ rows: BookingItem[]; loading?: boolean }>()
defineEmits<{ open: [key: string] }>()
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
  <div class="booking-table-wrap" :aria-busy="loading">
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
        <tr v-for="row in rows" :key="row.booking_key" @click="$emit('open', row.booking_key)">
          <td>
            <button
              type="button"
              class="table-booking-link"
              @click.stop="$emit('open', row.booking_key)"
            >
              {{ row.display_key }}</button
            ><span v-if="row.is_stale" class="row-stale-label">{{ t('bookingUi.stale') }}</span>
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
