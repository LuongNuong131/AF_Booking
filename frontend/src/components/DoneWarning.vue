<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { formatDateTime } from '../utils/dateTime'
import type { BookingSnapshot } from '../types/api.generated'
const { t } = useI18n(),
  auth = useAuthStore()
defineProps<{ snapshot: BookingSnapshot }>()
</script>
<template>
  <p
    v-if="snapshot.is_done && snapshot.last_agent?.id !== auth.user?.id"
    class="booking-warning done-warning"
    role="status"
  >
    {{
      t('done_warning', {
        user: snapshot.last_agent?.full_name || t('common.someone'),
        datetime: snapshot.done_at
          ? formatDateTime(snapshot.done_at, auth.timezone)
          : t('common.unknown'),
      })
    }}
  </p>
</template>
