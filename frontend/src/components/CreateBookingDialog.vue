<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { ElDialog } from 'element-plus'
import 'element-plus/es/components/dialog/style/css'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { useBookingsStore } from '../stores/bookings'
import { useFoldersStore } from '../stores/folders'
import { useUiStore } from '../stores/ui'
import { timeouts } from '../config/timeouts'
import { parseBookingKey } from '../utils/bookingKey'
import type { BookingCreateRequest, BookingItem, Suggestion } from '../types/api.generated'
import BaseIcon from './BaseIcon.vue'
import RequestStatus from './RequestStatus.vue'

const emit = defineEmits<{ close: []; open: [key: string] }>()
const { t } = useI18n(),
  bookings = useBookingsStore(),
  folders = useFoldersStore(),
  ui = useUiStore()
const input = ref(''),
  inputRef = ref<HTMLInputElement | null>(null),
  supplierName = ref(''),
  supplierType = ref<'hotel' | 'transportation'>('hotel'),
  confirmNew = ref(false),
  checkedKey = ref('')
const parsed = computed(() => {
  const value = parseBookingKey(input.value)
  return value && 'key' in value ? value : null
})
const lookup = useRequest((ctx, key: string) => bookings.lookup(ctx, key, true), {
  timeoutMs: timeouts.lookup,
  retry: true,
})
const create = useRequest(
  async ({ signal, timeoutMs }, body: BookingCreateRequest) =>
    (await api.post<BookingItem>('/bookings', body, { signal, timeout: timeoutMs })).data,
  { timeoutMs: timeouts.noteSave },
)
const current = computed(() => checkedKey.value === parsed.value?.key ? lookup.data.value : undefined)
const duplicate = computed(() => !!current.value?.exists || create.error.value?.code === 'BOOKING_EXISTS')
const existingGroup = computed(() => current.value?.group_exists &&
  current.value.group?.station_code === parsed.value?.station_code ? current.value.group : undefined)
const suggestions = computed<Suggestion[]>(() => {
  if (create.error.value?.code === 'NEW_BOOKING_NEEDS_CONFIRM') {
    const details = create.error.value.details as { suggestions?: Suggestion[] } | undefined
    return details?.suggestions ?? []
  }
  return current.value?.suggestions ?? []
})
const needsConfirmation = computed(() => suggestions.value.length > 0 || create.error.value?.code === 'NEW_BOOKING_NEEDS_CONFIRM')
const ready = computed(() => !!parsed.value && !!current.value && !duplicate.value &&
  (!!existingGroup.value || supplierName.value.trim().length >= 3) &&
  (!needsConfirmation.value || confirmNew.value))
const handledError = computed(() => ['BOOKING_EXISTS', 'NEW_BOOKING_NEEDS_CONFIRM'].includes(create.error.value?.code ?? ''))
let timer: ReturnType<typeof setTimeout> | undefined

async function check() {
  clearTimeout(timer)
  if (!parsed.value || create.pending.value) return
  const key = parsed.value.key
  checkedKey.value = ''
  const result = await lookup.run(key)
  if (result && key === parsed.value?.key) checkedKey.value = key
}
watch(() => parsed.value?.key, () => {
  clearTimeout(timer)
  lookup.cancel()
  lookup.error.value = null
  lookup.state.value = 'idle'
  checkedKey.value = ''
  create.error.value = null
  create.state.value = 'idle'
  confirmNew.value = false
  supplierName.value = ''
  supplierType.value = 'hotel'
  if (parsed.value) timer = setTimeout(() => void check(), timeouts.searchDebounce)
})
async function submit() {
  if (!ready.value || create.pending.value || !parsed.value) return
  const key = parsed.value.key
  const result = await create.run({
    booking_key: key,
    ...(!existingGroup.value ? {
      supplier_name: supplierName.value.trim(),
      supplier_type: supplierType.value,
    } : {}),
    confirm_new: confirmNew.value,
  })
  if (!result) return
  bookings.invalidate()
  folders.invalidate()
  ui.requestRefresh('retry')
  ui.notify(t('createBookingUi.created', { key: result.display_key }), 'success')
  emit('open', result.booking_key)
}
function close() {
  if (!create.pending.value) emit('close')
}
function openExisting(key: string) {
  if (!create.pending.value) {
    bookings.invalidate()
    emit('open', key)
  }
}
onScopeDispose(() => clearTimeout(timer))
</script>

<template>
  <ElDialog
    :model-value="true"
    :title="t('createBookingUi.title')"
    :show-close="false"
    :close-on-click-modal="!create.pending.value"
    :close-on-press-escape="!create.pending.value"
    width="560px"
    align-center
    class="create-booking-dialog"
    @opened="inputRef?.focus()"
    @update:model-value="close"
  >
    <template #header>
      <div class="dialog-heading">
        <h2>{{ t('createBookingUi.title') }}</h2>
        <button type="button" class="icon-button" :disabled="create.pending.value" :aria-label="t('common.close')" @click="close">
          <BaseIcon name="close" />
        </button>
      </div>
    </template>
    <p class="create-booking-intro">{{ t('createBookingUi.intro') }}</p>
    <form class="create-booking-form" :aria-label="t('createBookingUi.title')" @submit.prevent="submit">
      <label for="create-booking-key">{{ t('createBookingUi.bookingKey') }}</label>
      <div class="create-booking-input-row">
        <input
          id="create-booking-key"
          ref="inputRef"
          v-model="input"
          name="booking_key"
          maxlength="100"
          autocomplete="off"
          spellcheck="false"
          autocapitalize="characters"
          :placeholder="t('createBookingUi.placeholder')"
          :disabled="create.pending.value"
          :aria-invalid="!!input && !parsed"
          aria-describedby="create-booking-key-hint"
          required
        />
        <button type="button" class="button" :disabled="!parsed || lookup.pending.value || create.pending.value" @click="check">
          {{ t(lookup.pending.value ? 'createBookingUi.checking' : 'createBookingUi.check') }}
        </button>
      </div>
      <p id="create-booking-key-hint" class="create-booking-hint" :class="{ 'field-error': input && !parsed }">
        {{ t(input && !parsed ? 'createBookingUi.invalidKey' : 'createBookingUi.keyHint') }}
      </p>
      <RequestStatus :state="lookup.state.value" :error="lookup.error.value" @retry="check" />

      <div v-if="duplicate" class="create-booking-duplicate" role="alert">
        <BaseIcon name="folder" />
        <div>
          <strong>{{ t('createBookingUi.duplicateTitle') }}</strong>
          <p>{{ t('createBookingUi.duplicateBody') }}</p>
          <button type="button" class="text-button" @click="openExisting(parsed!.key)">{{ t('createBookingUi.openExisting') }}</button>
        </div>
      </div>
      <template v-else-if="current && parsed">
        <div class="create-booking-preview" role="status">
          <BaseIcon name="check" />
          <div><strong>{{ parsed.display_key }}</strong><span>{{ parsed.station_code }} · {{ parsed.period_label }}</span></div>
        </div>
        <div v-if="existingGroup" class="create-booking-supplier">
          <span>{{ t('bookingUi.supplierName') }}</span>
          <strong>{{ existingGroup.supplier_name }}</strong>
          <p>{{ t('createBookingUi.existingSupplier', { type: t(`supplier_types.${existingGroup.supplier_type}`) }) }}</p>
        </div>
        <fieldset v-else class="create-booking-new-supplier" :disabled="create.pending.value">
          <legend>{{ t('createBookingUi.newSupplier') }}</legend>
          <label for="create-booking-supplier">{{ t('bookingUi.supplierName') }}</label>
          <input id="create-booking-supplier" v-model="supplierName" name="supplier_name" minlength="3" maxlength="255" required :placeholder="t('createBookingUi.supplierPlaceholder')" />
          <label for="create-booking-type">{{ t('bookingUi.type') }}</label>
          <select id="create-booking-type" v-model="supplierType" name="supplier_type">
            <option value="hotel">{{ t('supplier_types.hotel') }}</option>
            <option value="transportation">{{ t('supplier_types.transportation') }}</option>
          </select>
          <p class="create-booking-hint">{{ t('createBookingUi.supplierHint') }}</p>
        </fieldset>
        <div v-if="needsConfirmation" class="create-booking-similar">
          <p>{{ t('createBookingUi.similarHint') }}</p>
          <ul v-if="suggestions.length">
            <li v-for="suggestion in suggestions" :key="suggestion.booking_key"><button type="button" class="text-button" @click="openExisting(suggestion.booking_key)">{{ suggestion.display_key }}</button></li>
          </ul>
          <label><input v-model="confirmNew" type="checkbox" :disabled="create.pending.value" />{{ t('createBookingUi.confirmNew') }}</label>
        </div>
      </template>
      <RequestStatus v-if="!handledError" :state="create.state.value" :error="create.error.value" @retry="submit" />
      <footer class="create-booking-actions">
        <button type="button" class="button" :disabled="create.pending.value" @click="close">{{ t('guardUi.cancel') }}</button>
        <button type="submit" class="button primary" :disabled="!ready || lookup.pending.value || create.pending.value">
          <span v-if="create.pending.value" class="button-spinner" aria-hidden="true" />
          {{ t(create.pending.value ? 'createBookingUi.adding' : 'createBookingUi.add') }}
        </button>
      </footer>
    </form>
  </ElDialog>
</template>

<style scoped>
.create-booking-intro { margin: 0 0 24px; color: var(--muted); line-height: 1.6; }
.create-booking-form { display: grid; gap: 10px; }
.create-booking-form > label, .create-booking-new-supplier > label { font-size: 14px; font-weight: 600; color: var(--ink); }
.create-booking-form input:not([type='checkbox']), .create-booking-form select { width: 100%; min-width: 0; min-height: 46px; padding: 11px 13px; color: var(--ink); background: var(--surface); border: 1px solid var(--line); border-radius: 10px; }
.create-booking-input-row { display: flex; gap: 8px; }
.create-booking-input-row .button { flex-shrink: 0; }
.create-booking-hint { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.6; }
.create-booking-hint.field-error { color: var(--danger); }
.create-booking-preview { display: flex; align-items: center; gap: 12px; padding: 16px; margin-top: 6px; border-radius: 12px; color: var(--primary); background: var(--primary-soft); }
.create-booking-preview strong, .create-booking-preview span { display: block; }
.create-booking-preview span { margin-top: 4px; font-size: 12px; color: var(--muted); }
.create-booking-supplier { padding: 8px 0; }
.create-booking-supplier > span { display: block; margin-bottom: 6px; color: var(--muted); font-size: 12px; }
.create-booking-supplier p { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
.create-booking-new-supplier { display: grid; gap: 10px; margin: 10px 0 0; padding: 18px; border: 1px solid var(--line); border-radius: 12px; }
.create-booking-new-supplier legend { padding: 0 6px; font-weight: 600; color: var(--ink); }
.create-booking-duplicate { display: flex; gap: 12px; padding: 18px; margin-top: 6px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface-soft); }
.create-booking-duplicate > .icon { flex-shrink: 0; color: var(--primary); }
.create-booking-duplicate p, .create-booking-similar p { margin: 6px 0 10px; color: var(--muted); line-height: 1.6; }
.create-booking-similar { padding: 16px; border: 1px solid var(--line); border-radius: 12px; }
.create-booking-similar ul { padding-left: 20px; }
.create-booking-similar label { display: flex; align-items: flex-start; gap: 10px; line-height: 1.5; }
.create-booking-similar input[type='checkbox'] { flex-shrink: 0; margin-top: 4px; }
.create-booking-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px; padding-top: 20px; border-top: 1px solid var(--line); }
@media (max-width: 480px) { .create-booking-input-row { flex-direction: column; } .create-booking-new-supplier { padding: 14px; } }
</style>
