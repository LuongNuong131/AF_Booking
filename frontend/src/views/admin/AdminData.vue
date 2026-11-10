<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { reminderParts, reminderInstant } from '../../utils/taskDates'
import { useAuthStore } from '../../stores/auth'
import { useRoute, useRouter } from 'vue-router'
import { ElDialog } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { api } from '../../api/client'
import { useRequest } from '../../composables/useRequest'
import { useViewRefresh } from '../../composables/useViewRefresh'
import { timeouts } from '../../config/timeouts'
import type { DataResource, JsonValue, Page } from '../../types/api.generated'
import PageControls from '../../components/PageControls.vue'
import RequestStatus from '../../components/RequestStatus.vue'
import EmptyState from '../../components/EmptyState.vue'
import AdminDeleteButton from '../../components/AdminDeleteButton.vue'
const { t } = useI18n(), route = useRoute(), router = useRouter(), auth = useAuthStore()
const resources = ref<DataResource[]>([]), resource = ref(String(route.query.resource || 'bookings')), q = ref(''), page = ref(1), editing = ref(false), selected = ref<Record<string, JsonValue> | null>(null)
const selection = ref<string[]>([]), bulkOpen = ref(false), bulkReason = ref('')
const form = reactive<Record<string, JsonValue>>({}), references = reactive<Record<string, Array<{ id: string; label: string }>>>({})
const definition = computed(() => resources.value.find(r => r.name === resource.value))
const fields = computed(() => definition.value?.fields.filter(f => !selected.value || (!f.readonly && f.kind !== 'password')) ?? [])
const columns = computed(() => definition.value?.fields.filter(f => f.kind !== 'password').slice(0, 6) ?? [])
const catalogs = useRequest(async ctx => (await api.get<DataResource[]>('/admin/data/resources', { signal: ctx.signal, timeout: ctx.timeoutMs })).data, { timeoutMs: timeouts.list, retry: true })
const request = useRequest(async ctx => (await api.get<Page<Record<string, JsonValue>>>(`/admin/data/${resource.value}`, { params: { q: q.value, page: page.value, size: 20 }, signal: ctx.signal, timeout: ctx.timeoutMs })).data, { timeoutMs: timeouts.list, retry: true })
const mutation = useRequest(async ctx => {
  const values = Object.fromEntries(fields.value.filter(f => form[f.name] !== undefined && (form[f.name] !== '' || (!f.required && ['text', 'textarea'].includes(f.kind ?? 'text')) || ['stale_after_hours', 'default_task_days'].includes(f.name))).map(f => [f.name, form[f.name] === '' ? null : f.kind === 'datetime' ? reminderInstant(String(form[f.name]).slice(0, 10), String(form[f.name]).slice(11, 16), auth.timezone) : form[f.name]]))
  const config = { signal: ctx.signal, timeout: ctx.timeoutMs }
  return selected.value ? (await api.patch(`/admin/data/${resource.value}/${selected.value.id}`, { values }, config)).data : (await api.post(`/admin/data/${resource.value}`, { values }, config)).data
}, { timeoutMs: timeouts.profile })
const bulk = useRequest(async ctx => (await api.post<{ removed: string[]; failed: Array<{ id: string; message: string }> }>(`/admin/data/${resource.value}/bulk-delete`, { ids: selection.value, reason: bulkReason.value.trim() }, { signal: ctx.signal, timeout: ctx.timeoutMs })).data, { timeoutMs: timeouts.export })
async function load(reset = false) { if (reset) page.value = 1; selection.value = []; await request.run() }
async function bulkDelete() { if (bulkReason.value.trim().length < 3 || bulk.pending.value) return; if (await bulk.run()) { bulkOpen.value = false; await load() } }
const selectedAll = computed(() => !!request.data.value?.items.length && request.data.value.items.every(r => selection.value.includes(String(r.id))))
function togglePage() { selection.value = selectedAll.value ? [] : request.data.value?.items.map(r => String(r.id)) ?? [] }
async function open(row: Record<string, JsonValue> | null = null) {
  selected.value = row
  for (const k of Object.keys(form)) delete form[k]
  for (const f of definition.value?.fields ?? []) form[f.name] = row?.[f.name] ?? (f.kind === 'boolean' ? ['is_active', 'recurring_enabled'].includes(f.name) : f.options?.[0] ?? '')
  for (const f of fields.value.filter(f => f.kind === 'datetime')) { if (typeof form[f.name] === 'string' && String(form[f.name]).includes('Z')) { const parts = reminderParts(String(form[f.name]), auth.timezone); form[f.name] = `${parts.date}T${parts.time}` } }
  if (!row && resource.value === 'bookings') form.supplier_type = 'hotel'
  mutation.error.value = null; mutation.state.value = 'idle'; editing.value = true
  await Promise.all(fields.value.filter(f => f.reference).map(f => searchReference(f.reference!)))
}
async function searchReference(resource: string, q = '') {
  const value = await api.get<Page<{ id: string; label: string }>>(`/admin/data/${resource}`, { params: { q, size: 50 } }).catch(() => null)
  references[resource] = value?.data.items ?? []
}
async function save() { if (mutation.pending.value) return; if (await mutation.run()) { editing.value = false; await load() } }
watch(resource, async () => { editing.value = false; q.value = ''; await router.replace({ name: 'admin-data', query: { resource: resource.value } }); void load(true) })
watch(() => route.query.resource, value => { if (typeof value === 'string' && resources.value.some(r => r.name === value)) resource.value = value })
useViewRefresh(() => load())
onMounted(async () => { resources.value = await catalogs.run() ?? []; if (!resources.value.some(r => r.name === resource.value)) resource.value = 'bookings'; await load() })
const text = (v: JsonValue | undefined) => v === null || v === undefined ? '—' : typeof v === 'boolean' ? t(v ? 'adminUi.enabled' : 'adminUi.disabled') : String(v)
</script>
<template>
  <section class="data-console">
    <header class="admin-section-heading"><div><h2>{{ t('dataUi.title') }}</h2><p class="muted">{{ t('dataUi.intro') }}</p></div><RouterLink class="button" :to="{ name: 'admin-trash' }">{{ t('adminUi.trash') }}</RouterLink></header>
    <form class="workflow-controls" @submit.prevent="load(true)"><label>{{ t('dataUi.resource') }}<select v-model="resource"><option v-for="r in resources" :key="r.name" :value="r.name">{{ t(`dataUi.resources.${r.name}`) }}</option></select></label><label>{{ t('opsUi.search') }}<input v-model="q" maxlength="100" /></label><button class="button" type="submit" :disabled="request.pending.value">{{ t('adminUi.apply') }}</button><button class="button primary" type="button" :disabled="!definition" @click="open()">{{ t('dataUi.create') }}</button><button class="button danger" type="button" :disabled="!selection.length" @click="bulkReason = ''; bulkOpen = true">{{ t('dataUi.deleteSelected', { count: selection.length }) }}</button></form>
    <RequestStatus :state="catalogs.state.value" :error="catalogs.error.value" @retry="catalogs.run" /><RequestStatus :state="request.state.value" :error="request.error.value" @retry="load()" />
    <RequestStatus :state="bulk.state.value" :error="bulk.error.value" />
    <div v-if="bulk.data.value?.failed.length" class="inline-error" role="alert"><p>{{ t('dataUi.partialDelete') }}</p><ul><li v-for="failure in bulk.data.value.failed" :key="failure.id">#{{ failure.id }} · {{ failure.message }}</li></ul></div>
    <div v-if="request.data.value?.items.length" class="admin-table-wrap"><table class="admin-table"><thead><tr><th><input type="checkbox" :checked="selectedAll" :aria-label="t('dataUi.selectAll')" @change="togglePage" /></th><th>#</th><th v-for="f in columns" :key="f.name">{{ t(`dataUi.fields.${f.name}`) }}</th><th>{{ t('adminUi.actions') }}</th></tr></thead><tbody><tr v-for="row in request.data.value.items" :key="String(row.id)"><td><input v-model="selection" type="checkbox" :value="String(row.id)" :aria-label="String(row.label)" /></td><td>{{ row.id }}</td><td v-for="f in columns" :key="f.name" class="data-cell"><span>{{ f.name === 'supplier_type' && row[f.name] ? t(`supplier_types.${row[f.name]}`) : text(row[f.name]) }}</span></td><td class="data-row-actions"><button type="button" class="text-button" @click="open(row)">{{ t('adminUi.edit') }}</button><AdminDeleteButton :resource="resource" :identifier="String(row.id)" :label="String(row.label)" @deleted="load()" /></td></tr></tbody></table></div>
    <EmptyState v-else-if="request.state.value === 'success'" :title="t('common.noRecords')" :description="t('common.noRecordsHint')" />
    <PageControls :page="page" :size="20" :total="request.data.value?.total ?? 0" @change="page = $event; load()" />
    <ElDialog :model-value="editing" :title="t(selected ? 'dataUi.edit' : 'dataUi.create')" width="640px" :close-on-click-modal="!mutation.pending.value" :close-on-press-escape="!mutation.pending.value" :show-close="!mutation.pending.value" @update:model-value="!mutation.pending.value && (editing = $event)">
      <form class="admin-edit-form data-edit-form" @submit.prevent="save"><p class="muted">{{ t(`dataUi.resources.${resource}`) }} <span v-if="selected">· #{{ selected.id }}</span></p>
        <template v-for="f in fields" :key="f.name"><label v-if="f.kind === 'boolean'" class="data-checkbox"><input v-model="form[f.name]" type="checkbox" :disabled="mutation.pending.value" />{{ t(`dataUi.fields.${f.name}`) }}</label><label v-else>{{ t(`dataUi.fields.${f.name}`) }}<template v-if="f.reference"><input type="search" :placeholder="t('dataUi.findReference')" @input="searchReference(f.reference!, ($event.target as HTMLInputElement).value)" /><select v-model="form[f.name]" :required="f.required" :disabled="mutation.pending.value"><option value="">{{ t('dataUi.choose') }}</option><option v-if="form[f.name] && !references[f.reference]?.some(r => String(r.id) === String(form[f.name]))" :value="String(form[f.name])">#{{ form[f.name] }}</option><option v-for="r in references[f.reference]" :key="r.id" :value="Number(r.id)">{{ r.label }} · #{{ r.id }}</option></select></template><select v-else-if="f.kind === 'select'" v-model="form[f.name]" :required="f.required" :disabled="mutation.pending.value"><option v-for="option in f.options?.filter(value => selected || resource !== 'bookings' || f.name !== 'supplier_type' || value !== 'unclassified')" :key="option" :value="option">{{ f.name === 'supplier_type' ? t(`supplier_types.${option}`) : option }}</option></select><textarea v-else-if="f.kind === 'textarea'" v-model="form[f.name] as string" :required="f.required" :maxlength="f.max_length ?? undefined" rows="4" :disabled="mutation.pending.value" /><input v-else-if="f.kind === 'number'" v-model.number="form[f.name]" type="number" min="0" :required="f.required" :disabled="mutation.pending.value" /><input v-else v-model="form[f.name]" :type="f.kind === 'datetime' ? 'datetime-local' : f.kind === 'password' ? 'password' : 'text'" :required="f.required" :maxlength="f.max_length ?? undefined" :disabled="mutation.pending.value" /></label></template>
        <RequestStatus :state="mutation.state.value" :error="mutation.error.value" @retry="save" /><div class="admin-form-actions"><button type="button" class="button" :disabled="mutation.pending.value" @click="editing = false">{{ t('folderUi.cancel') }}</button><button type="submit" class="button primary" :disabled="mutation.pending.value">{{ t(mutation.pending.value ? 'folderUi.saving' : 'dataUi.save') }}</button></div>
      </form>
    </ElDialog>
    <ElDialog :model-value="bulkOpen" :title="t('dataUi.moveToTrash')" width="520px" :close-on-click-modal="!bulk.pending.value" :show-close="!bulk.pending.value" :close-on-press-escape="!bulk.pending.value" @update:model-value="!bulk.pending.value && (bulkOpen = $event)"><form class="admin-edit-form" @submit.prevent="bulkDelete"><p>{{ t('dataUi.bulkHint', { count: selection.length }) }}</p><label>{{ t('adminUi.reason') }}<textarea v-model="bulkReason" minlength="3" maxlength="255" required rows="3" /></label><RequestStatus :state="bulk.state.value" :error="bulk.error.value" /><div class="admin-form-actions"><button type="button" class="button" :disabled="bulk.pending.value" @click="bulkOpen = false">{{ t('folderUi.cancel') }}</button><button type="submit" class="button danger" :disabled="bulk.pending.value || bulkReason.trim().length < 3">{{ t('dataUi.moveToTrash') }}</button></div></form></ElDialog>
  </section>
</template>
