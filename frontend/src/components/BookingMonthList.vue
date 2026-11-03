<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useVirtualList } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import type { MonthRow, BookingItem } from '../types/api.generated'
import { formatDateTime } from '../utils/dateTime'
import StatusTag from './StatusTag.vue'
const props = defineProps<{
    months: (MonthRow & Partial<Pick<BookingItem, 'supplier' | 'station_code'>>)[]
  }>(),
  emit = defineEmits<{ open: [key: string] }>()
const { t } = useI18n(),
  auth = useAuthStore(),
  limit = ref(20)
watch(
  () => props.months[0]?.booking_key,
  () => {
    limit.value = 20
  },
)
const shown = computed(() => props.months.slice(0, limit.value))
const { list, containerProps, wrapperProps } = useVirtualList(shown, {
  itemHeight: 120,
  overscan: 3,
})
const displayed = computed(() =>
  props.months.length > 50 ? list.value.map((x) => x.data) : shown.value,
)
</script>
<template>
  <div
    class="month-list"
    :class="{ virtual: months.length > 50 }"
    v-bind="months.length > 50 ? containerProps : {}"
    :aria-label="t('folderUi.months')"
  >
    <div v-bind="months.length > 50 ? wrapperProps : {}">
      <button
        v-for="month in displayed"
        :key="month.booking_key"
        type="button"
        class="month-row"
        data-search-result
        @click="emit('open', month.booking_key)"
      >
        <header>
          <strong>{{ month.period_label }}</strong
          ><StatusTag :status="month.last_status" />
        </header>
        <span class="month-key">{{ month.display_key }}</span>
        <span v-if="month.supplier" class="month-supplier"
          >{{ month.supplier.name }} · {{ month.station_code }} ·
          {{ t(`supplier_types.${month.supplier.type}`) }}</span
        >
        <div class="month-row-footer">
          <span>{{ month.last_agent?.full_name || t('common.unknown') }}</span
          ><span v-if="month.is_stale" class="row-stale-label">{{ t('bookingUi.stale') }}</span
          ><time :datetime="month.updated_at">{{
            formatDateTime(month.updated_at, auth.timezone)
          }}</time>
        </div>
      </button>
    </div>
  </div>
  <div v-if="months.length" class="month-list-footer">
    <span>{{
      t('folderUi.showingMonths', { shown: Math.min(limit, months.length), total: months.length })
    }}</span
    ><button v-if="limit < months.length" type="button" class="text-button" @click="limit += 20">
      {{ t('folderUi.moreMonths') }}
    </button>
  </div>
  <p v-else class="muted">{{ t('folderUi.noMonths') }}</p>
</template>
