<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { formatDateTime } from '../utils/dateTime'
import { useAuthStore } from '../stores/auth'
import type { DailyBooking } from '../types/api.generated'
import StatusTag from './StatusTag.vue'
defineProps<{ rows: DailyBooking[] }>()
const { t } = useI18n(),
  auth = useAuthStore()
</script>
<template>
  <div class="booking-table-wrap">
    <table class="booking-table">
      <thead>
        <tr>
          <th>{{ t('bookingUi.booking') }}</th>
          <th>{{ t('bookingUi.supplier') }}</th>
          <th>{{ t('bookingUi.station') }}</th>
          <th>{{ t('bookingUi.type') }}</th>
          <th>{{ t('bookingUi.status') }}</th>
          <th>{{ t('bookingUi.agent') }}</th>
          <th>{{ t('bookingUi.updatedAt') }}</th>
          <th>{{ t('opsUi.notes') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.booking_key">
          <td>
            <RouterLink :to="{ name: 'booking', params: { key: row.booking_key } }">{{
              row.display_key
            }}</RouterLink>
          </td>
          <td>{{ row.supplier_name }}</td>
          <td>{{ row.station_code }}</td>
          <td>{{ t(`supplier_types.${row.supplier_type}`) }}</td>
          <td><StatusTag :status="row.status" /></td>
          <td>{{ row.agent?.full_name ?? '—' }}</td>
          <td>{{ formatDateTime(row.updated_at, auth.timezone) }}</td>
          <td>{{ row.note_count }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!rows.length" class="muted">{{ t('opsUi.noRows') }}</p>
  </div>
</template>
