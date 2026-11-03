<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useFoldersStore } from '../stores/folders'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import type { GroupInfo, SupplierType } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
const props = defineProps<{ cw: string; name: string; type: SupplierType }>(),
  emit = defineEmits<{ updated: [group: GroupInfo] }>()
const { t } = useI18n(),
  auth = useAuthStore(),
  store = useFoldersStore(),
  editing = ref(false),
  name = ref(props.name),
  type = ref(props.type)
const allowed = computed(() => ['admin', 'qc'].includes(auth.user?.role ?? ''))
const request = useRequest(
  (ctx, body: { supplier_name: string; supplier_type: SupplierType }) =>
    store.rename(ctx, props.cw, body),
  { timeoutMs: timeouts.profile },
)
watch(
  () => [props.cw, props.name, props.type],
  () => {
    if (!editing.value) {
      name.value = props.name
      type.value = props.type
    }
  },
)
function start() {
  name.value = props.name
  type.value = props.type
  editing.value = true
}
async function save() {
  if (name.value.trim().length < 3 || request.pending.value) return
  const result = await request.run({
    supplier_name: name.value.trim(),
    supplier_type: type.value,
  })
  if (result) {
    editing.value = false
    emit('updated', result)
  }
}
</script>
<template>
  <div v-if="allowed" class="supplier-editor">
    <button v-if="!editing" type="button" class="text-button" @click="start">
      {{ t('folderUi.editSupplier') }}
    </button>
    <form v-else @submit.prevent="save">
      <label
        >{{ t('bookingUi.supplierName')
        }}<input v-model="name" minlength="3" maxlength="255" required /></label
      ><label
        >{{ t('bookingUi.type')
        }}<select v-model="type">
          <option value="hotel">{{ t('supplier_types.hotel') }}</option>
          <option value="transportation">
            {{ t('supplier_types.transportation') }}
          </option>
        </select></label
      >
      <div class="supplier-editor-actions">
        <button
          type="submit"
          class="button primary"
          :disabled="request.pending.value || name.trim().length < 3"
        >
          {{ t('folderUi.saveSupplier') }}</button
        ><button
          type="button"
          class="button"
          :disabled="request.pending.value"
          @click="editing = false"
        >
          {{ t('common.close') }}
        </button>
      </div>
      <RequestStatus :state="request.state.value" :error="request.error.value" @retry="save" />
    </form>
  </div>
</template>
