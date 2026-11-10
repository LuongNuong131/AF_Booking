<script setup lang="ts">
import { ref } from 'vue'
import { ElDialog } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import RequestStatus from './RequestStatus.vue'
const props = defineProps<{ resource: string; identifier: string | number; label: string; disabled?: boolean }>()
const emit = defineEmits<{ deleted: [] }>()
const { t } = useI18n(), open = ref(false), reason = ref('')
const request = useRequest(async ({ signal, timeoutMs }) => (await api.delete(`/admin/data/${props.resource}/${props.identifier}`, { data: { reason: reason.value.trim() }, signal, timeout: timeoutMs })).data, { timeoutMs: timeouts.export })
async function remove() { if (reason.value.trim().length < 3 || request.pending.value) return; if (await request.run()) { open.value = false; emit('deleted') } }
</script>
<template>
  <span class="admin-delete-action" @click.stop>
    <button type="button" class="text-button danger-text" :disabled="disabled" @click="open = true; reason = ''; request.error.value = null; request.state.value = 'idle'">{{ t('dataUi.delete') }}</button>
    <ElDialog :model-value="open" :title="t('dataUi.moveToTrash')" width="520px" :close-on-click-modal="!request.pending.value" :show-close="!request.pending.value" :close-on-press-escape="!request.pending.value" @update:model-value="!request.pending.value && (open = $event)">
      <form class="admin-edit-form" @submit.prevent="remove"><strong>{{ label }}</strong><p>{{ t('dataUi.deleteHint') }}</p><label>{{ t('adminUi.reason') }}<textarea v-model="reason" required minlength="3" maxlength="255" rows="3" :disabled="request.pending.value" /></label><RequestStatus :state="request.state.value" :error="request.error.value" @retry="remove" /><div class="admin-form-actions"><button type="button" class="button" :disabled="request.pending.value" @click="open = false">{{ t('folderUi.cancel') }}</button><button type="submit" class="button danger" :disabled="reason.trim().length < 3 || request.pending.value">{{ t('dataUi.moveToTrash') }}</button></div></form>
    </ElDialog>
  </span>
</template>
