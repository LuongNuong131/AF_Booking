<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { useShortcuts } from '../composables/useShortcuts'
import { formatDateTime } from '../utils/dateTime'
import { parseInvoiceInput, validInvoice, INVOICE_PATTERN } from '../utils/invoice'
import type { Invoice, InvoiceChange, InvoiceWarning } from '../types/api.generated'
const props = withDefaults(
  defineProps<{
    items: Invoice[]
    state: string
    modelValue?: InvoiceChange
    required?: boolean
    readonly?: boolean
    canSave?: boolean
    pattern?: string
    max?: number
    warnings?: InvoiceWarning[]
  }>(),
  { pattern: INVOICE_PATTERN, max: 20 },
)
const emit = defineEmits<{ 'update:modelValue': [InvoiceChange]; save: [] }>()
const { t } = useI18n(),
  auth = useAuthStore(),
  ui = useUiStore(),
  input = ref<HTMLInputElement | null>(null),
  raw = ref('')
const change = computed(() => props.modelValue ?? {}),
  retained = computed(() =>
    props.items.filter((i) => !change.value.remove_ids?.includes(i.id)),
  ),
  pending = computed(() => change.value.add ?? []),
  noInvoice = computed(() => change.value.no_invoice ?? props.state === 'no_invoice')
const total = computed(
  () =>
    retained.value.length +
    pending.value.filter((n) => !retained.value.some((i) => i.invoice_number === n)).length,
)
const changed = computed(
  () =>
    !!pending.value.length ||
    !!change.value.remove_ids?.length ||
    (change.value.no_invoice !== undefined &&
      change.value.no_invoice !== (props.state === 'no_invoice')),
)
const invalid = computed(() => pending.value.filter((n) => !validInvoice(n, props.pattern)))
function update(value: InvoiceChange) {
  emit('update:modelValue', { ...change.value, ...value })
}
function add() {
  const values = parseInvoiceInput(raw.value)
  if (!values.length) return
  update({
    add: [
      ...new Set([
        ...pending.value,
        ...values.filter((n) => !retained.value.some((i) => i.invoice_number === n)),
      ]),
    ],
    no_invoice: false,
  })
  raw.value = ''
}
function toggle() {
  if (total.value) return
  update({ no_invoice: !noInvoice.value })
}
function remove(item: Invoice) {
  if (window.confirm(t('invoiceUi.removeConfirm', { number: item.invoice_number })))
    update({
      remove_ids: [...new Set([...(change.value.remove_ids ?? []), item.id])],
    })
}
const canRemove = (item: Invoice) =>
  item.id > 0 &&
  !props.readonly &&
  (item.added_by.id === auth.user?.id || ['admin', 'qc'].includes(auth.user?.role ?? ''))
function paste(event: ClipboardEvent) {
  event.preventDefault()
  raw.value += event.clipboardData?.getData('text') ?? ''
  add()
}
async function copy(value: string) {
  try {
    await navigator.clipboard.writeText(value)
    ui.notify(t('invoiceUi.copied'), 'success')
  } catch {
    ui.notify(t('invoiceUi.copyFailed'), 'error')
  }
}
if (!props.readonly)
  useShortcuts(
    'invoice-editor',
    [
      { key: 'alt+i', allowInput: true, run: () => input.value?.focus() },
      { key: 'alt+n', allowInput: true, run: toggle },
    ],
    { enabled: () => !props.readonly },
  )
</script>
<template>
  <section class="invoice-panel" :aria-label="t('invoice_label')">
    <h3>{{ t('invoice_label') }}</h3>
    <div class="invoice-chips">
      <span
        v-for="item in retained"
        :key="item.id"
        class="invoice-chip"
        :title="`${item.added_by.full_name} · ${formatDateTime(item.created_at, auth.timezone)}`"
        ><button type="button" class="text-button" @click="copy(item.invoice_number)">
          {{ item.invoice_number }}</button
        ><button
          v-if="canRemove(item)"
          type="button"
          class="text-button"
          :aria-label="t('invoiceUi.remove', { number: item.invoice_number })"
          @click="remove(item)"
        >
          ×
        </button></span
      >
      <span
        v-for="number in pending"
        :key="number"
        class="invoice-chip"
        :class="{ invalid: !validInvoice(number, pattern) }"
        >{{ number
        }}<button
          v-if="!readonly"
          type="button"
          class="text-button"
          :aria-label="t('invoiceUi.remove', { number })"
          @click="update({ add: pending.filter((n) => n !== number) })"
        >
          ×
        </button></span
      >
    </div>
    <template v-if="!readonly">
      <label class="field-label"
        >{{ t('invoice_label')
        }}<input
          ref="input"
          v-model="raw"
          :disabled="noInvoice"
          :placeholder="t('invoice_placeholder')"
          @keydown.enter.prevent="add"
          @paste="paste"
          @blur="add"
      /></label>
      <label class="invoice-none"
        ><input type="checkbox" :checked="noInvoice" :disabled="total > 0" @change="toggle" />{{
          t('no_invoice_checkbox')
        }}</label
      >
      <p v-if="total" class="input-hint">{{ t('no_invoice_disabled_hint') }}</p>
      <p v-if="required && !total && !noInvoice" class="field-error">
        {{ t('invoice_required_hint') }}
      </p>
      <p v-for="number in invalid" :key="number" class="field-error">
        {{ t('invoice_invalid', { value: number }) }}
      </p>
      <p v-if="total > max" class="field-error">
        {{ t('invoice_limit', { max }) }}
      </p>
      <button
        v-if="canSave"
        type="button"
        class="button"
        :disabled="!changed || !!invalid.length || total > max || !!raw.trim()"
        @click="emit('save')"
      >
        {{ t('invoiceUi.save') }}
      </button>
    </template>
    <p v-else-if="!items.length" class="muted">
      {{ t(state === 'no_invoice' ? 'invoice_state_none' : 'invoice_state_unknown') }}
    </p>
    <p v-for="warning in warnings ?? []" :key="warning.invoice_number" class="booking-warning">
      {{
        t('invoice_duplicate_elsewhere', {
          number: warning.invoice_number,
          count: warning.booking_keys.length,
          keys: '',
        })
      }}
      <RouterLink
        v-for="key in warning.booking_keys"
        :key="key"
        :to="{ name: 'booking', params: { key } }"
        >{{ key.replace(/^CW/, 'CW ') }}
      </RouterLink>
    </p>
  </section>
</template>
