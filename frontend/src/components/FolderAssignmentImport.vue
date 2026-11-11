<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import type { AssignmentImportResult } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
const emit = defineEmits<{ imported: [] }>()
const { t } = useI18n()
const workbook = ref(''), fileName = ref(''), fileError = ref(false)
const mapping = ref<Record<string, string>>({})
const users = ref<Array<{ username: string; full_name: string }>>([])
const preview = ref<AssignmentImportResult | null>(null)
const options = useRequest(async ({ signal }) => (await api.get<{
  users: typeof users.value; agent_map: Record<string, string>
}>('/folder-assignments/options', { signal })).data, { timeoutMs: 15000, retry: true })
async function loadOptions() {
  const result = await options.run()
  if (result) { users.value = result.users; mapping.value = result.agent_map }
}
onMounted(() => { void loadOptions() })
const request = useRequest(async ({ signal }, apply: boolean, source: string, agent_map: Record<string, string>) =>
  (await api.post<AssignmentImportResult>('/admin/folder-assignments/import', {
    workbook: source, agent_map, apply,
  }, { signal, timeout: 65000 })).data, { timeoutMs: 65000 })
watch([workbook, mapping], () => { preview.value = null }, { deep: true })
async function loadFile(event: Event) {
  workbook.value = ''
  fileError.value = false
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 500000) { fileError.value = true; return }
  try {
    const bytes = new Uint8Array(await file.arrayBuffer())
    let binary = ''
    for (const byte of bytes) binary += String.fromCharCode(byte)
    fileName.value = file.name
    workbook.value = btoa(binary)
  } catch { fileError.value = true }
}
async function run(apply: boolean) {
  if (request.pending.value || (apply && (!preview.value || preview.value.applied))) return
  const source = workbook.value
  const result = await request.run(apply, source, { ...mapping.value })
  if (result && source === workbook.value) {
    preview.value = result
    if (apply) emit('imported')
  }
}
</script>
<template>
  <section class="admin-panel assignment-import">
    <h2>{{ t('assignmentUi.importTitle') }}</h2>
    <p>{{ t('assignmentUi.importHint') }}</p>
    <label class="field-label">{{ t('assignmentUi.file') }}
      <input type="file" accept=".xlsx" :disabled="request.pending.value" @change="loadFile" />
    </label>
    <p v-if="fileError" role="alert">{{ t('assignmentUi.fileError') }}</p>
    <RequestStatus :state="options.state.value" :error="options.error.value" @retry="loadOptions" />
    <details v-if="Object.keys(mapping).length">
      <summary>{{ t('assignmentUi.mapping') }}</summary>
      <div class="assignment-mapping">
        <label v-for="(_, alias) in mapping" :key="alias" class="field-label">{{ alias }}
          <select v-model="mapping[alias]" :aria-label="String(alias)" :disabled="request.pending.value">
            <option value="">{{ t('assignmentUi.unassigned') }}</option>
            <option v-if="mapping[alias] && !users.some(u => u.username === mapping[alias])" :value="mapping[alias]">{{ mapping[alias] }} ({{ t('assignmentUi.missingUser') }})</option>
            <option v-for="user in users" :key="user.username" :value="user.username">{{ user.full_name }} ({{ user.username }})</option>
          </select>
        </label>
      </div>
    </details>
    <button class="button" type="button" :disabled="!workbook || request.pending.value || options.state.value !== 'success'" @click="run(false)">{{ t('importUi.preview') }}</button>
    <RequestStatus :state="request.state.value" :error="request.error.value" @retry="run(false)" />
    <div v-if="preview" class="assignment-preview" role="status">
      <strong>{{ fileName }}</strong>
      <p>{{ t('assignmentUi.importCounts', { rows: preview.source_rows, duplicates: preview.duplicate_rows, count: preview.rows.length }) }}</p>
      <p>{{ t('assignmentUi.importPlan', { bookings: preview.new_bookings, folders: preview.new_folders, updated: preview.updated_folders, preserved: preview.preserved_folders }) }}</p>
      <details>
        <summary>{{ t('assignmentUi.reviewRows', { count: preview.rows.filter(r => r.review).length }) }}</summary>
        <div class="admin-table-wrap"><table><thead><tr>
          <th>{{ t('bookingUi.bookingNumber') }}</th><th>{{ t('assignmentUi.owner') }}</th><th>{{ t('bookingUi.type') }}</th><th>{{ t('assignmentUi.review') }}</th>
        </tr></thead><tbody><tr v-for="row in preview.rows" :key="row.booking_key">
          <td>{{ row.booking_key }}<br />{{ row.supplier_name }}</td><td>{{ row.username || t('assignmentUi.unassigned') }}<br />{{ row.source_agent }}</td><td>{{ t(`supplier_types.${row.supplier_type}`) }}</td><td>{{ row.review || '—' }}</td>
        </tr></tbody></table></div>
      </details>
      <p v-if="preview.applied">{{ t('assignmentUi.importDone') }}</p>
      <button v-else type="button" class="button primary" :disabled="request.pending.value" @click="run(true)">{{ t('importUi.apply') }}</button>
    </div>
  </section>
</template>
<style scoped>
.assignment-import { display: grid; gap: 1rem; }
.assignment-mapping { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 230px), 1fr)); gap: .8rem; padding-block: 1rem; }
.assignment-preview { display: grid; gap: .6rem; }
.assignment-preview td { max-width: 450px; overflow-wrap: anywhere; }
.assignment-import summary { cursor: pointer; }
</style>
