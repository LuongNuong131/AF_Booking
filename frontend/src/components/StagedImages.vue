<script setup lang="ts">
import { onScopeDispose, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import type { AttachmentStorageInfo } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
const props = defineProps<{ modelValue: File[]; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [files: File[]] }>()
const { t } = useI18n(), validation = ref(''), previews = ref<{ file: File; url: string }[]>([])
const config = useRequest(async ({ signal, timeoutMs }) => (await api.get<AttachmentStorageInfo>('/attachments/config', { signal, timeout: timeoutMs })).data, { timeoutMs: timeouts.list })
function release() { previews.value.forEach(p => URL.revokeObjectURL(p.url)) }
watch(() => props.modelValue, files => {
  release()
  previews.value = files.map(file => ({ file, url: URL.createObjectURL(file) }))
}, { immediate: true })
onScopeDispose(release)
function open(event: Event) { if ((event.target as HTMLDetailsElement).open && !config.data.value) void config.run() }
function choose(event: Event) {
  const input = event.target as HTMLInputElement, files = [...(input.files ?? [])], caps = config.data.value
  input.value = ''; validation.value = ''
  if (props.disabled || !caps?.enabled || !files.length) return
  const combined = [...props.modelValue, ...files]
  if (combined.length > caps.max_files || files.some(file => !file.size || file.size > caps.max_file_bytes || !caps.mime_types.includes(file.type))) {
    validation.value = t('noteImageUi.limits'); return
  }
  emit('update:modelValue', combined)
}
</script>
<template>
  <details class="staged-images" @toggle="open">
    <summary>{{ t('ticketCompose.images') }} ({{ modelValue.length }})</summary>
    <RequestStatus :state="config.state.value" :error="config.error.value" @retry="config.run" />
    <p v-if="config.data.value && !config.data.value.enabled" class="muted" role="status">{{ t('noteImageUi.unavailable') }}</p>
    <label v-if="config.data.value?.enabled" class="note-image-input">{{ t('noteImageUi.choose') }}<input type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple :disabled="disabled || modelValue.length >= config.data.value.max_files" @change="choose" /></label>
    <p class="input-hint">{{ t('noteImageUi.limits') }} {{ t('ticketCompose.imageHint') }}</p>
    <p v-if="validation" role="alert" class="field-error">{{ validation }}</p>
    <div class="note-image-grid"><figure v-for="(preview, index) in previews" :key="preview.url">
      <img :src="preview.url" :alt="preview.file.name" />
      <figcaption>{{ preview.file.name }} <button type="button" class="text-button" :disabled="disabled" :aria-label="t('ticketCompose.removeImage', { name: preview.file.name })" @click="emit('update:modelValue', modelValue.filter((_, i) => i !== index))">{{ t('ticketCompose.remove') }}</button></figcaption>
    </figure></div>
  </details>
</template>
