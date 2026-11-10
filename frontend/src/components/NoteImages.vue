<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import type { Attachment, AttachmentStorageInfo } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
const props = defineProps<{ noteId: number; files: Attachment[]; canAdd: boolean }>()
const { t } = useI18n(), files = ref([...props.files]), urls = ref<Record<number, string>>({}),
  selected = ref<File[]>([]), validation = ref(''), expanded = ref(false)
watch(() => props.files, value => { files.value = [...value] })
const validFiles = computed(() => files.value.filter(file => file.mime_type.startsWith('image/')))
const config = useRequest(async ({ signal, timeoutMs }) => (await api.get<AttachmentStorageInfo>('/attachments/config', { signal, timeout: timeoutMs })).data, { timeoutMs: timeouts.list })
const preview = useRequest(async ({ signal, timeoutMs }) => {
  for (const file of validFiles.value) {
    if (urls.value[file.id]) continue
    const response = await api.get<Blob>(`/attachments/${file.id}/content`, { responseType: 'blob', signal, timeout: timeoutMs })
    urls.value[file.id] = URL.createObjectURL(response.data)
  }
  return true
}, { timeoutMs: timeouts.noteSave })
const upload = useRequest(async ({ signal, timeoutMs }) => {
  for (const file of [...selected.value]) {
    const result = (await api.post<Attachment>(`/notes/${props.noteId}/attachments`, file, {
      params: { file_name: file.name }, headers: { 'Content-Type': file.type }, signal, timeout: timeoutMs,
    })).data
    if (!files.value.some(f => f.id === result.id)) files.value.push(result)
    selected.value = selected.value.filter(f => f !== file)
  }
  return true
}, { timeoutMs: timeouts.noteSave })
async function open(event: Event) {
  expanded.value = (event.target as HTMLDetailsElement).open
  if (!expanded.value) return
  if (props.canAdd && !config.data.value) await config.run()
  if (validFiles.value.length) void preview.run()
}
async function choose(event: Event) {
  const input = event.target as HTMLInputElement, chosen = [...(input.files ?? [])], caps = config.data.value
  input.value = ''; validation.value = ''
  if (!caps?.enabled || !chosen.length) return
  if (chosen.length + files.value.length > caps.max_files || chosen.some(file => file.size > caps.max_file_bytes || !caps.mime_types.includes(file.type))) {
    validation.value = t('noteImageUi.limits'); return
  }
  selected.value = chosen
  await send()
}
async function send() { if (await upload.run()) void preview.run() }
onScopeDispose(() => { Object.values(urls.value).forEach(url => URL.revokeObjectURL(url)) })
</script>
<template>
  <details v-if="validFiles.length || canAdd" class="note-images" @toggle="open">
    <summary>{{ t(validFiles.length ? 'noteImageUi.view' : 'noteImageUi.add', { count: validFiles.length }) }}</summary>
    <div class="note-image-grid" v-if="validFiles.length"><figure v-for="file in validFiles" :key="file.id">
      <a v-if="urls[file.id]" :href="urls[file.id]" target="_blank" rel="noopener"><img :src="urls[file.id]" :alt="file.file_name" loading="lazy" /></a>
      <span v-else class="muted">{{ file.file_name }}</span>
      <figcaption><span>{{ file.file_name }}</span><a v-if="urls[file.id]" :href="urls[file.id]" :download="file.file_name" class="text-button">{{ t('noteImageUi.download') }}</a></figcaption>
    </figure></div>
    <RequestStatus :state="preview.state.value" :error="preview.error.value" @retry="preview.run" />
    <template v-if="canAdd">
      <RequestStatus :state="config.state.value" :error="config.error.value" @retry="config.run" />
      <p v-if="config.data.value && !config.data.value.enabled" class="muted" role="status">{{ t('noteImageUi.unavailable') }}</p>
      <label v-else-if="config.data.value?.enabled && files.length < config.data.value.max_files" class="note-image-input">{{ t('noteImageUi.choose') }}<input type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple :disabled="upload.pending.value" @change="choose" /></label>
      <p v-if="config.data.value?.enabled" class="input-hint">{{ t('noteImageUi.limits') }}</p>
      <p v-if="validation" class="field-error" role="alert">{{ validation }}</p>
      <RequestStatus :state="upload.state.value" :error="upload.error.value" @retry="send" />
    </template>
  </details>
</template>
