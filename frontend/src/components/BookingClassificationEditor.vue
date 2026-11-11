<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElDialog } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { useBookingsStore } from '../stores/bookings'
import { useFoldersStore } from '../stores/folders'
import { timeouts } from '../config/timeouts'
import type { BookingItem, SupplierType } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
const props = defineProps<{ bookingKey: string; type: SupplierType; compact?: boolean }>()
const emit = defineEmits<{ updated: [booking: BookingItem] }>()
const { t } = useI18n(), open = ref(false), selected = ref(props.type), current = ref(props.type), saved = ref(false)
watch(() => [props.bookingKey, props.type], () => { current.value = props.type; selected.value = props.type; open.value = false; request.cancel() })
const request = useRequest(async ({ signal, timeoutMs }, type: string, expected: SupplierType) => (await api.patch<BookingItem>(`/bookings/${props.bookingKey}/classification`, { supplier_type: type, expected_type: expected }, { signal, timeout: timeoutMs })).data, { timeoutMs: timeouts.profile })
const valid = computed(() => ['hotel', 'transportation'].includes(selected.value) && selected.value !== current.value)
function start() { selected.value = current.value; saved.value = false; request.state.value = 'idle'; request.error.value = null; open.value = true }
async function save() {
  if (!valid.value || request.pending.value) return
  const value = await request.run(selected.value, current.value)
  if (value) {
    current.value = value.supplier.type; open.value = false; saved.value = true
    useBookingsStore().invalidate(); useFoldersStore().invalidate(); emit('updated', value)
  }
}
</script>
<template>
  <span class="booking-classification-action" @click.stop @keydown.stop>
    <button type="button" class="button classification-trigger" :class="{ compact, unclassified: current === 'unclassified' }" @click="start">
      {{ t(current === 'unclassified' ? 'classificationUi.classify' : 'classificationUi.edit') }}
    </button>
    <span v-if="saved && !compact" class="supplier-save-success" role="status">{{ t('classificationUi.saved') }}</span>
    <ElDialog :model-value="open" :title="t('classificationUi.title')" width="480px" :close-on-click-modal="!request.pending.value" :close-on-press-escape="!request.pending.value" :show-close="!request.pending.value" @update:model-value="!request.pending.value && (open = $event)">
      <form class="classification-form" @submit.prevent="save">
        <p class="classification-booking-key">{{ bookingKey }}</p>
        <p class="muted">{{ t('classificationUi.hint') }}</p>
        <label>{{ t('bookingUi.type') }}<select v-model="selected" :aria-label="t('bookingUi.type')" :disabled="request.pending.value">
          <option v-if="current === 'unclassified'" value="unclassified" disabled>{{ t('supplier_types.unclassified') }}</option>
          <option value="hotel">{{ t('supplier_types.hotel') }}</option><option value="transportation">{{ t('supplier_types.transportation') }}</option>
        </select></label>
        <RequestStatus :state="request.state.value" :error="request.error.value" @retry="save" />
        <div class="admin-form-actions"><button type="button" class="button" :disabled="request.pending.value" @click="open = false">{{ t('folderUi.cancel') }}</button><button type="submit" class="button primary" :disabled="!valid || request.pending.value">{{ t(request.pending.value ? 'folderUi.saving' : 'folderUi.saveClassification') }}</button></div>
      </form>
    </ElDialog>
  </span>
</template>
