<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../../api/client'
import { useRequest } from '../../composables/useRequest'
import type { BookingImportResult } from '../../types/api.generated'
import RequestStatus from '../../components/RequestStatus.vue'
const { t } = useI18n()
const data = ref(''), preview = ref<BookingImportResult | null>(null)
const fileError = ref(false)
async function loadFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  fileError.value = file.size > 500000
  if (fileError.value) return
  try { data.value = await file.text() } catch { fileError.value = true }
}
const request = useRequest(async ({ signal }, apply: boolean, source: string) =>
  (await api.post<BookingImportResult>('/admin/bookings/import', { data: source, apply }, { signal, timeout: 65000 })).data,
  { timeoutMs: 65000 },
)
watch(data, () => { preview.value = null })
async function run(apply: boolean) {
  if (request.pending.value || (apply && (!preview.value || preview.value.applied))) return
  const source = data.value
  const result = await request.run(apply, source)
  if (result && source === data.value) preview.value = result
}
</script>
<template>
  <section class="admin-panel">
    <h2>{{ t('importUi.title') }}</h2>
    <p>{{ t('importUi.hint') }}</p>
    <label class="field-label">{{ t('importUi.file') }}<input type="file" accept=".txt,.csv,.tsv,text/plain,text/csv" :disabled="request.pending.value" @change="loadFile" /></label>
    <p v-if="fileError" role="alert">{{ t('importUi.fileError') }}</p>
    <label class="field-label">{{ t('importUi.data') }}
      <textarea v-model="data" rows="12" maxlength="500000" :disabled="request.pending.value" spellcheck="false" />
    </label>
    <button class="button" type="button" :disabled="!data.trim() || request.pending.value" @click="run(false)">{{ t('importUi.preview') }}</button>
    <RequestStatus :state="request.state.value" :error="request.error.value" />
    <div v-if="preview" role="status">
      <p>{{ t('importUi.counts', { rows: preview.source_rows, unique: preview.unique_bookings, duplicates: preview.duplicate_rows }) }}</p>
      <p>{{ t('importUi.plan', { created: preview.new_bookings, existing: preview.existing_bookings, folders: preview.new_folders }) }}</p>
      <p v-if="preview.applied">{{ t('importUi.done') }}</p>
      <button v-else class="button primary" type="button" :disabled="request.pending.value" @click="run(true)">{{ t('importUi.apply') }}</button>
    </div>
  </section>
</template>
