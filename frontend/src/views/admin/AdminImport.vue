<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../../api/client'
import { useRequest } from '../../composables/useRequest'
import type { BookingImportResult } from '../../types/api.generated'
import RequestStatus from '../../components/RequestStatus.vue'
import MonthlyBookingPanel from '../../components/MonthlyBookingPanel.vue'
import FolderAssignmentImport from '../../components/FolderAssignmentImport.vue'
const { t } = useI18n()
const data = ref(''), preview = ref<BookingImportResult | null>(null)
const fileError = ref(false)
const stationSource = ref<'strict' | 'station_code' | 'booking_number'>('strict')
const fillMissing = ref(false)
const monthly = ref<InstanceType<typeof MonthlyBookingPanel> | null>(null)
const errorRow = () => {
  const details = request.error.value?.details
  return details && typeof details === 'object' && 'row' in details && typeof details.row === 'number' ? details.row : null
}
async function loadFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  fileError.value = file.size > 500000
  if (fileError.value) return
  try { data.value = await file.text() } catch { fileError.value = true }
}
const request = useRequest(async ({ signal }, apply: boolean, source: string, station_source: typeof stationSource.value, fill_missing_supplier: boolean) =>
  (await api.post<BookingImportResult>('/admin/bookings/import', { data: source, apply, station_source, fill_missing_supplier }, { signal, timeout: 65000 })).data,
  { timeoutMs: 65000 },
)
watch([data, stationSource, fillMissing], () => { preview.value = null })
async function run(apply: boolean) {
  if (request.pending.value || (apply && (!preview.value || preview.value.applied))) return
  const source = data.value
  const result = await request.run(apply, source, stationSource.value, fillMissing.value)
  if (result && source === data.value) {
    preview.value = result
    if (apply) void monthly.value?.refresh()
  }
}
</script>
<template>
  <div class="import-page">
  <FolderAssignmentImport @imported="monthly?.refresh()" />
  <section class="admin-panel import-panel">
    <div class="import-heading">
    <h2>{{ t('importUi.title') }}</h2>
    <a class="button" href="/booking-template.csv" download>{{ t('importUi.template') }}</a>
    </div>
    <p>{{ t('importUi.hint') }}</p>
    <div class="csv-reference">
      <h3>{{ t('importUi.columnsTitle') }}</h3>
      <code>Booking Number,Suppliers,Station Code,Supplier Type,Recurring</code>
      <p>{{ t('importUi.columnsHint') }}</p>
      <pre>Booking Number,Suppliers,Station Code,Supplier Type,Recurring
CW9999001-SGN-2610,"Example Hotel, Saigon",SGN,hotel,true
CWXXXX-LAS-2610,Example Supplier,LAS,,false</pre>
    </div>
    <label class="field-label">{{ t('importUi.file') }}<input type="file" accept=".txt,.csv,.tsv,text/plain,text/csv" :disabled="request.pending.value" @change="loadFile" /></label>
    <p v-if="fileError" role="alert">{{ t('importUi.fileError') }}</p>
    <fieldset class="import-options" :disabled="request.pending.value">
      <legend>{{ t('importUi.options') }}</legend>
      <label class="field-label">{{ t('importUi.stationPolicy') }}
        <select v-model="stationSource">
          <option value="strict">{{ t('importUi.strict') }}</option>
          <option value="station_code">{{ t('importUi.useStation') }}</option>
          <option value="booking_number">{{ t('importUi.useBooking') }}</option>
        </select>
      </label>
      <label class="recurring-toggle"><input v-model="fillMissing" type="checkbox" />{{ t('importUi.fillMissing') }}</label>
      <p>{{ t('importUi.reviewHint') }}</p>
    </fieldset>
    <label class="field-label">{{ t('importUi.data') }}
      <textarea v-model="data" rows="12" maxlength="500000" :disabled="request.pending.value" spellcheck="false" />
    </label>
    <button class="button" type="button" :disabled="!data.trim() || request.pending.value" @click="run(false)">{{ t('importUi.preview') }}</button>
    <RequestStatus :state="request.state.value" :error="request.error.value" />
    <p v-if="errorRow()" class="field-error">{{ t('importUi.errorRow', { row: errorRow() }) }}</p>
    <div v-if="preview" class="import-preview" role="status">
      <p>{{ t('importUi.counts', { rows: preview.source_rows, unique: preview.unique_bookings, duplicates: preview.duplicate_rows }) }}</p>
      <p>{{ t('importUi.plan', { created: preview.new_bookings, existing: preview.existing_bookings, folders: preview.new_folders }) }}</p>
      <details v-if="preview.adjustments?.length" class="import-changes">
        <summary>{{ t('importUi.changes', { count: preview.adjustments.length }) }}</summary>
        <div class="admin-table-wrap"><table><thead><tr><th>{{ t('importUi.row') }}</th><th>{{ t('importUi.field') }}</th><th>{{ t('importUi.before') }}</th><th>{{ t('importUi.after') }}</th></tr></thead><tbody>
          <tr v-for="(change, index) in preview.adjustments" :key="index"><td>{{ change.row }}</td><td>{{ change.field }}</td><td>{{ change.before || '—' }}</td><td>{{ change.after }}</td></tr>
        </tbody></table></div>
      </details>
      <p v-if="preview.applied">{{ t('importUi.done') }}</p>
      <button v-else class="button primary" type="button" :disabled="request.pending.value" @click="run(true)">{{ t('importUi.apply') }}</button>
    </div>
  </section>
  <MonthlyBookingPanel ref="monthly" />
  </div>
</template>
