<script setup lang="ts">
import { onMounted, onScopeDispose, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import type { Attachment } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
const props = defineProps<{ files: Attachment[] }>()
const { t } = useI18n(), urls = ref<Record<number, string>>({})
const preview = useRequest(async ({ signal, timeoutMs }) => {
  for (const file of props.files) {
    if (urls.value[file.id]) continue
    const response = await api.get<Blob>(`/attachments/${file.id}/content`, { responseType: 'blob', signal, timeout: timeoutMs })
    if (!signal.aborted) urls.value[file.id] = URL.createObjectURL(response.data)
  }
  return true
}, { timeoutMs: timeouts.noteSave })
function release() { Object.values(urls.value).forEach(URL.revokeObjectURL); urls.value = {} }
watch(() => props.files, () => { preview.cancel(); release(); void preview.run() })
onMounted(() => { if (props.files.length) void preview.run() })
onScopeDispose(release)
</script>
<template>
  <div class="ticket-attachments">
    <div class="note-image-grid"><figure v-for="file in files" :key="file.id">
      <a v-if="urls[file.id]" :href="urls[file.id]" target="_blank" rel="noopener"><img :src="urls[file.id]" :alt="file.file_name" loading="lazy" /></a>
      <span v-else>{{ file.file_name }}</span>
      <figcaption>{{ file.file_name }} <a v-if="urls[file.id]" :href="urls[file.id]" :download="file.file_name" class="text-button">{{ t('noteImageUi.download') }}</a></figcaption>
    </figure></div>
    <RequestStatus :state="preview.state.value" :error="preview.error.value" @retry="preview.run" />
  </div>
</template>
