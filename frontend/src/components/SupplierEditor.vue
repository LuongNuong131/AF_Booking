<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useFoldersStore } from '../stores/folders'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import type { FolderPatch, GroupInfo, SupplierType } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
const props = withDefaults(defineProps<{
  cw: string; name: string; type: SupplierType; recurring?: boolean
}>(), { recurring: true })
const emit = defineEmits<{ updated: [group: GroupInfo] }>()
const { t } = useI18n(), auth = useAuthStore(), store = useFoldersStore()
const trigger = ref<HTMLButtonElement | null>(null)
const editing = ref<'classification' | 'details' | null>(null)
const name = ref(props.name), type = ref(props.type), recurring = ref(props.recurring)
const saved = ref<'classificationSaved' | 'supplierSaved' | null>(null)
const canEditDetails = computed(() => ['admin', 'qc'].includes(auth.user?.role ?? ''))
const request = useRequest(
  (ctx, cw: string, body: FolderPatch) => store.rename(ctx, cw, body),
  { timeoutMs: timeouts.profile },
)
const valid = computed(() => editing.value === 'details'
  ? name.value.trim().length >= 3
  : ['hotel', 'transportation'].includes(type.value) && type.value !== props.type)
watch(() => props.cw, () => {
  request.cancel()
  editing.value = null
  saved.value = null
})
function start(mode: 'classification' | 'details') {
  request.cancel()
  request.error.value = null
  request.state.value = 'idle'
  saved.value = null
  name.value = props.name
  type.value = props.type
  recurring.value = props.recurring
  editing.value = mode
}
async function close() {
  editing.value = null
  await nextTick()
  trigger.value?.focus()
}
async function save() {
  if (!valid.value || request.pending.value) return
  const cw = props.cw, mode = editing.value
  const body: FolderPatch = mode === 'classification'
    ? { supplier_type: type.value }
    : { supplier_name: name.value.trim(), supplier_type: type.value, recurring_enabled: recurring.value }
  const result = await request.run(cw, body)
  if (result && cw === props.cw) {
    editing.value = null
    saved.value = mode === 'classification' ? 'classificationSaved' : 'supplierSaved'
    emit('updated', result)
    await nextTick()
    trigger.value?.focus()
  }
}
</script>
<template>
  <div class="supplier-editor">
    <div v-if="!editing" class="supplier-editor-triggers">
      <button type="button" ref="trigger" class="button classification-trigger" @click="start('classification')">
        <span aria-hidden="true">↔</span>{{ t('folderUi.editClassification') }}
      </button>
      <button v-if="canEditDetails" type="button" class="text-button" @click="start('details')">
        {{ t('folderUi.editSupplier') }}
      </button>
    </div>
    <p v-if="saved" role="status" class="supplier-save-success">{{ t(`folderUi.${saved}`) }}</p>
    <form v-if="editing" class="supplier-edit-form" :aria-label="t(editing === 'classification' ? 'folderUi.editClassification' : 'folderUi.editSupplier')" :aria-busy="request.pending.value" @submit.prevent="save">
      <fieldset :disabled="request.pending.value">
        <legend>{{ t(editing === 'classification' ? 'folderUi.editClassification' : 'folderUi.editSupplier') }}</legend>
        <label v-if="editing === 'details'">{{ t('bookingUi.supplierName') }}
          <input v-model="name" minlength="3" maxlength="255" required />
        </label>
        <label>{{ t('bookingUi.type') }}
          <select v-model="type" :aria-label="t('bookingUi.type')">
            <option v-if="editing === 'details' || type === 'unclassified'" value="unclassified" :disabled="editing === 'classification'">{{ t('supplier_types.unclassified') }}</option>
            <option value="hotel">{{ t('supplier_types.hotel') }}</option>
            <option value="transportation">{{ t('supplier_types.transportation') }}</option>
          </select>
        </label>
        <label v-if="editing === 'details'" class="recurring-toggle">
          <input v-model="recurring" type="checkbox" />{{ t('monthlyUi.recurring') }}
        </label>
        <p class="supplier-scope-hint">{{ t('folderUi.classificationHint') }}</p>
        <div class="supplier-editor-actions">
          <button type="submit" class="button primary" :disabled="!valid">
            {{ t(request.pending.value ? 'folderUi.saving' : editing === 'classification' ? 'folderUi.saveClassification' : 'folderUi.saveSupplier') }}
          </button>
          <button type="button" class="button" @click="close">{{ t('folderUi.cancel') }}</button>
        </div>
      </fieldset>
      <RequestStatus :state="request.state.value" :error="request.error.value" @retry="save" />
    </form>
  </div>
</template>
