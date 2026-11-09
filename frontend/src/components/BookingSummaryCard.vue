<script setup lang="ts">
import { computed } from 'vue'
import { folderKey } from '../utils/folderKey'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { parseBookingKey } from '../utils/bookingKey'
import { formatDateTime } from '../utils/dateTime'
import type { BookingLookup } from '../types/api.generated'
import BookingKeyText from './BookingKeyText.vue'
import TaskButton from './TaskButton.vue'
import StatusTag from './StatusTag.vue'
import LockBadge from './LockBadge.vue'
import DoneWarning from './DoneWarning.vue'
import InvoicePanel from './InvoicePanel.vue'
import SupplierEditor from './SupplierEditor.vue'
defineEmits<{ supplierUpdated: [] }>()
const { t } = useI18n(),
  auth = useAuthStore()
const props = defineProps<{ booking: BookingLookup }>()
const identity = computed(() =>
  props.booking.booking_key ? parseBookingKey(props.booking.booking_key) : null,
)
</script>
<template>
  <section
    v-if="booking.booking_key"
    class="booking-summary-card"
    :aria-label="t('bookingUi.bookingSummary')"
  >
    <header>
      <BookingKeyText :booking-key="booking.booking_key" /><span
        v-if="!booking.exists"
        class="new-booking-tag"
        >{{ t('bookingUi.new') }}</span
      ><StatusTag v-if="booking.snapshot?.last_status" :status="booking.snapshot.last_status" />
    </header>
    <h2 v-if="booking.group">{{ booking.group.supplier_name }}</h2>
    <SupplierEditor
      v-if="booking.group"
      :cw="folderKey(booking.group)"
      :name="booking.group.supplier_name"
      :type="booking.group.supplier_type"
      :recurring="booking.group.recurring_enabled"
      @updated="$emit('supplierUpdated')"
    />
    <div class="summary-metadata">
      <span v-if="booking.group">{{ t(`supplier_types.${booking.group.supplier_type}`) }}</span
      ><span>{{
        booking.snapshot?.station_code ||
        (identity && 'station_code' in identity
          ? identity.station_code
          : booking.group?.station_code)
      }}</span
      ><span>{{ booking.snapshot?.period_label || identity?.period_label }}</span>
    </div>
    <dl v-if="booking.snapshot" class="booking-facts">
      <div>
        <dt>{{ t('bookingUi.position') }}</dt>
        <dd>{{ booking.snapshot.last_position || t('common.unknown') }}</dd>
      </div>
      <div>
        <dt>{{ t('bookingUi.lastAgent') }}</dt>
        <dd>
          {{ booking.snapshot.last_agent?.full_name || t('common.unknown') }}
        </dd>
      </div>
      <div>
        <dt>{{ t('bookingUi.updatedAt') }}</dt>
        <dd>
          {{ formatDateTime(booking.snapshot.updated_at, auth.timezone) }}
        </dd>
      </div>
    </dl>
    <p v-else class="muted new-history">{{ t('new_booking') }}</p>
    <p v-if="booking.format_warning" class="booking-warning" role="status">
      {{ booking.format_warning }}
    </p>
    <DoneWarning v-if="booking.snapshot" :snapshot="booking.snapshot" /><LockBadge
      :booking-key="booking.booking_key"
    />
    <TaskButton
      v-if="booking.booking_key && booking.exists"
      :booking-key="booking.booking_key"
      :count="booking.my_tasks?.length"
    />
    <InvoicePanel
      v-if="booking.snapshot"
      readonly
      :items="booking.invoices ?? []"
      :state="booking.snapshot.invoice_state"
    />
    <slot />
  </section>
</template>
