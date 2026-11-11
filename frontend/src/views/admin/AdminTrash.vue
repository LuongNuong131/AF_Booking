<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElDialog } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { api } from '../../api/client'
import { useRequest } from '../../composables/useRequest'
import { timeouts } from '../../config/timeouts'
import { useAuthStore } from '../../stores/auth'
import { formatDateTime } from '../../utils/dateTime'
import type { Page, TrashItem, PurgePreview } from '../../types/api.generated'
import RequestStatus from '../../components/RequestStatus.vue'
import PageControls from '../../components/PageControls.vue'
import EmptyState from '../../components/EmptyState.vue'
const { t } = useI18n(), auth = useAuthStore(), q = ref(''), page = ref(1), selected = ref<number[]>([]), confirmation = ref(''), previewIds = ref<number[]>([]), reviewing = ref(false), success = ref(false)
const request = useRequest(async ctx => (await api.get<Page<TrashItem>>('/admin/data/trash', { params: { q: q.value, page: page.value, size: 20 }, signal: ctx.signal, timeout: ctx.timeoutMs })).data, { timeoutMs: timeouts.list, retry: true })
const preview = useRequest(async (ctx, selectedIds: number[], all = false) => {
  const ids = [...selectedIds]
  if (all) {
    ids.length = 0
    for (let p = 1; ; p++) {
      const value = await api.get<Page<TrashItem>>('/admin/data/trash', { params: { page: p, size: 100 }, signal: ctx.signal, timeout: ctx.timeoutMs })
      if (value.data.total > 2000) throw new Error(t('dataUi.batchLimit'))
      ids.push(...value.data.items.map(r => r.id))
      if (ids.length >= value.data.total || !value.data.items.length) break
    }
  }
  previewIds.value = ids
  return (await api.post<PurgePreview>('/admin/data/trash/preview', ids, { signal: ctx.signal, timeout: ctx.timeoutMs })).data
}, { timeoutMs: timeouts.export })
const mutation = useRequest(async (ctx, mode: 'restore' | 'purge', id?: number) => mode === 'restore' ? (await api.post(`/admin/data/trash/${id}/restore`, {}, { signal: ctx.signal, timeout: ctx.timeoutMs })).data : (await api.post('/admin/data/trash/purge', { ids: previewIds.value, confirmation: confirmation.value, preview_token: preview.data.value?.token }, { signal: ctx.signal, timeout: ctx.timeoutMs })).data, { timeoutMs: timeouts.export })
async function load(reset = false) { if (reset) page.value = 1; selected.value = []; await request.run() }
async function restore(id: number) { if (mutation.pending.value) return; if (await mutation.run('restore', id)) await load() }
async function review(all = false) {
  if (preview.pending.value || mutation.pending.value) return
  success.value = false; confirmation.value = ''; preview.data.value = undefined; previewIds.value = [...selected.value]
  reviewing.value = true
  if (all || previewIds.value.length) await preview.run(previewIds.value, all)
}
async function purge() { if (confirmation.value !== 'DELETE' || !preview.data.value || preview.data.value.blockers.length || mutation.pending.value) return; if (await mutation.run('purge')) { reviewing.value = false; success.value = true; await load(true) } }
const allSelected = computed(() => !!request.data.value?.items.length && request.data.value.items.every(r => selected.value.includes(r.id)))
function selectAll() { selected.value = allSelected.value ? [] : request.data.value?.items.map(r => r.id) ?? [] }
onMounted(() => load())
</script>
<template>
  <section class="trash-console"><header class="admin-section-heading"><div><h2>{{ t('adminUi.trash') }}</h2><p class="muted">{{ t('dataUi.trashHint') }}</p></div><button class="button danger" :disabled="!request.data.value?.total || preview.pending.value" @click="review(true)">{{ t('dataUi.emptyTrash') }}</button></header>
    <form class="workflow-controls" @submit.prevent="load(true)"><label>{{ t('opsUi.search') }}<input v-model="q" maxlength="100" /></label><button type="submit" class="button">{{ t('adminUi.apply') }}</button><button type="button" class="button danger" :disabled="!selected.length || preview.pending.value" @click="review()">{{ t('dataUi.purgeSelected', { count: selected.length }) }}</button></form>
    <p v-if="success" role="status" class="supplier-save-success">{{ t('dataUi.purged') }}</p><RequestStatus :state="request.state.value" :error="request.error.value" @retry="load()" /><RequestStatus :state="mutation.state.value" :error="mutation.error.value" />
    <div v-if="request.data.value?.items.length" class="admin-table-wrap"><table class="admin-table"><thead><tr><th><input type="checkbox" :checked="allSelected" :aria-label="t('dataUi.selectAll')" @change="selectAll" /></th><th>{{ t('dataUi.resource') }}</th><th>{{ t('dataUi.record') }}</th><th>{{ t('dataUi.deletedAt') }}</th><th>{{ t('adminUi.reason') }}</th><th>{{ t('adminUi.actions') }}</th></tr></thead><tbody><tr v-for="row in request.data.value.items" :key="row.id"><td><input v-model="selected" type="checkbox" :value="row.id" :aria-label="row.label" /></td><td>{{ t(`dataUi.resources.${row.resource}`) }}</td><td class="data-cell">{{ row.label }}<small>#{{ row.record_id }}</small></td><td>{{ formatDateTime(row.created_at, auth.timezone) }}</td><td>{{ row.reason }}</td><td><button type="button" class="text-button" :disabled="mutation.pending.value" @click="restore(row.id)">{{ t('dataUi.restore') }}</button></td></tr></tbody></table></div><EmptyState v-else-if="request.state.value === 'success'" :title="t('dataUi.trashEmpty')" :description="t('dataUi.trashHint')" />
    <PageControls :page="page" :size="20" :total="request.data.value?.total ?? 0" @change="page = $event; load()" />
    <ElDialog :model-value="reviewing" :title="t('dataUi.purgeTitle')" width="660px" :show-close="!mutation.pending.value" :close-on-click-modal="false" :close-on-press-escape="!mutation.pending.value" @update:model-value="!mutation.pending.value && (reviewing = $event)"><p>{{ t('dataUi.purgeHint') }}</p><RequestStatus :state="preview.state.value" :error="preview.error.value" @retry="preview.run(previewIds)" /><template v-if="preview.data.value"><dl class="purge-counts"><div v-for="(count, key) in preview.data.value.counts" :key="key"><dt>{{ t(`dataUi.resources.${key}`, String(key)) }}</dt><dd>{{ count }}</dd></div></dl><div v-if="preview.data.value.blockers.length" class="inline-error" role="alert"><p>{{ t('dataUi.blocked') }}</p><ul><li v-for="item in preview.data.value.blockers" :key="item">{{ item }}</li></ul></div><form v-else class="admin-edit-form" @submit.prevent="purge"><label>{{ t('dataUi.confirmDelete') }}<input v-model="confirmation" autocomplete="off" :disabled="mutation.pending.value" /></label><RequestStatus :state="mutation.state.value" :error="mutation.error.value" /><div class="admin-form-actions"><button type="button" class="button" :disabled="mutation.pending.value" @click="reviewing = false">{{ t('folderUi.cancel') }}</button><button type="submit" class="button danger" :disabled="confirmation !== 'DELETE' || mutation.pending.value">{{ t('dataUi.purgeNow') }}</button></div></form></template><p v-else-if="!preview.pending.value" class="muted">{{ t('dataUi.batchLimit') }}</p></ElDialog>
  </section>
</template>
