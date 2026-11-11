<script setup lang="ts">
import { computed, nextTick, onMounted, onScopeDispose, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useRealtimeStore } from '../stores/realtime'
import { useRequest } from '../composables/useRequest'
import { useViewRefresh } from '../composables/useViewRefresh'
import { folderKey } from '../utils/folderKey'
import type { FolderAssignmentItem, FolderAssignmentPatch, Page, SupplierType } from '../types/api.generated'
import BaseIcon from './BaseIcon.vue'
import RequestStatus from './RequestStatus.vue'
import SupplierFolder from './SupplierFolder.vue'
const emit = defineEmits<{ open: [key: string] }>()
const { t } = useI18n(), auth = useAuthStore(), realtime = useRealtimeStore()
const scope = ref('mine'), region = ref(''), query = ref(''), agent = ref(''), page = ref(1)
const monthsPane = ref<HTMLElement | null>(null)
const selected = ref<FolderAssignmentItem | null>(null), editing = ref<FolderAssignmentItem | null>(null)
const draftOwner = ref<number | null>(null), draftRegion = ref(''), draftReview = ref(''), draftType = ref<SupplierType>('unclassified')
const supervisor = computed(() => ['admin', 'qc'].includes(auth.user?.role ?? ''))
const options = useRequest(async ({ signal }) => (await api.get<{
  users: Array<{ id: number; username: string; full_name: string }>; regions: string[]
}>('/folder-assignments/options', { signal })).data, { timeoutMs: 15000, retry: true })
const request = useRequest(async ({ signal }, filters: Record<string, string | number>) =>
  (await api.get<Page<FolderAssignmentItem>>('/folder-assignments', { signal, params: filters })).data,
  { timeoutMs: 15000, retry: true })
const saveRequest = useRequest(async ({ signal }, id: number, body: FolderAssignmentPatch) =>
  (await api.patch(`/folder-assignments/${id}`, body, { signal })).data as { version: number }, { timeoutMs: 15000 })
const data = computed(() => request.data.value)
const sections = computed(() => {
  const groups = new Map<string, { region: string | null; items: FolderAssignmentItem[] }>()
  for (const item of data.value?.items ?? []) {
    const key = item.region ?? ''
    if (!groups.has(key)) groups.set(key, { region: item.region, items: [] })
    groups.get(key)!.items.push(item)
  }
  return [...groups.values()]
})
async function load() {
  await request.run({ scope: scope.value, region: region.value, q: query.value, page: page.value, size: 20,
    ...(agent.value && scope.value !== 'mine' ? { agent_id: agent.value } : {}) })
  if (data.value && page.value > 1 && !data.value.items.length) page.value = Math.max(1, Math.ceil(data.value.total / 20))
}
watch([scope, region, agent], () => { if (page.value === 1) void load(); else page.value = 1 })
watch(page, () => { void load() })
function search() { if (page.value === 1) void load(); else page.value = 1 }
onMounted(() => { void load(); void options.run() })
useViewRefresh(() => { void load(); void options.run() })
let refreshTimer: ReturnType<typeof setTimeout> | undefined
watch(() => realtime.revision, () => {
  clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => { void load() }, 250)
})
onScopeDispose(() => clearTimeout(refreshTimer))
async function selectFolder(item: FolderAssignmentItem) {
  selected.value = selected.value?.group_id === item.group_id ? null : item
  await nextTick()
  monthsPane.value?.scrollIntoView({ block: 'start' })
}
function edit(item: FolderAssignmentItem) {
  editing.value = item
  draftOwner.value = item.assigned_to?.id ?? null
  draftRegion.value = item.region ?? ''
  draftReview.value = item.review ?? ''
  draftType.value = item.folder.supplier_type
}
async function save() {
  const item = editing.value
  if (!item || saveRequest.pending.value) return
  const body: FolderAssignmentPatch = { supplier_type: draftType.value, expected_version: item.version, expected_supplier_type: item.folder.supplier_type }
  if (supervisor.value) Object.assign(body, { assigned_to: draftOwner.value, region: draftRegion.value, review: draftReview.value })
  if (await saveRequest.run(item.group_id, body)) {
    editing.value = null
    await load()
    void options.run()
  }
}
</script>
<template>
  <section class="admin-panel folder-assignments" :aria-label="t('assignmentUi.title')">
    <header class="assignment-heading">
      <div><h2>{{ t('assignmentUi.title') }}</h2><p>{{ t('assignmentUi.hint') }}</p></div>
      <button type="button" class="button" :disabled="request.pending.value" @click="load">{{ t('assignmentUi.refresh') }}</button>
    </header>
    <form class="assignment-filters" @submit.prevent="search">
      <label>{{ t('assignmentUi.scope') }}<select v-model="scope" :aria-label="t('assignmentUi.scope')">
        <option value="mine">{{ t('assignmentUi.mine') }}</option><option value="all">{{ t('assignmentUi.all') }}</option>
        <option value="unassigned">{{ t('assignmentUi.unassigned') }}</option><option value="review">{{ t('assignmentUi.review') }}</option>
      </select></label>
      <label>{{ t('assignmentUi.region') }}<select v-model="region" :aria-label="t('assignmentUi.region')"><option value="">{{ t('assignmentUi.allRegions') }}</option>
        <option v-for="value in options.data.value?.regions" :key="value" :value="value">{{ value }}</option>
      </select></label>
      <label v-if="scope !== 'mine'">{{ t('assignmentUi.owner') }}<select v-model="agent"><option value="">{{ t('assignmentUi.everyone') }}</option>
        <option v-for="user in options.data.value?.users" :key="user.id" :value="String(user.id)">{{ user.full_name }}</option>
      </select></label>
      <label>{{ t('assignmentUi.search') }}<input v-model="query" maxlength="100" type="search" /></label>
      <button class="button" type="submit">{{ t('assignmentUi.searchAction') }}</button>
    </form>
    <RequestStatus :state="options.state.value" :error="options.error.value" @retry="options.run()" />
    <RequestStatus :state="request.state.value" :error="request.error.value" @retry="load" />
    <p v-if="data" role="status">{{ t('assignmentUi.total', { count: data.total }) }}</p>
    <p v-if="data && !data.items.length">{{ t('assignmentUi.empty') }}</p>
    <div v-for="section in sections" :key="section.region ?? ''" class="assignment-section">
      <h3>{{ section.region || t('assignmentUi.noRegion') }}</h3>
      <div class="assignment-grid">
        <article v-for="item in section.items" :key="item.group_id" class="assignment-card">
          <button type="button" class="assignment-open" :aria-expanded="selected?.group_id === item.group_id" @click="selectFolder(item)">
            <BaseIcon name="folder" /><span><strong>{{ item.folder.station_code }} · {{ item.folder.supplier_type === 'hotel' ? 'HT' : item.folder.supplier_type === 'transportation' ? 'GT' : t('assignmentUi.unknownType') }}</strong>
              <span>{{ item.folder.supplier_name }}</span></span>
          </button>
          <p>{{ item.assigned_to?.full_name || t('assignmentUi.unassigned') }}</p>
          <p>{{ t('assignmentUi.folderCounts', { months: item.folder.booking_count, open: item.folder.open_count }) }}</p>
          <p v-if="item.review" class="assignment-review">{{ t('assignmentUi.review') }}: {{ item.review }}</p>
          <details v-if="Object.keys(item.metadata).length"><summary>{{ t('assignmentUi.sourceDetails') }}</summary>
            <dl><template v-for="(value, name) in item.metadata" :key="name"><dt>{{ name }}</dt><dd>{{ value }}</dd></template></dl>
          </details>
          <button type="button" class="text-button" @click="edit(item)">{{ t(supervisor ? 'assignmentUi.edit' : 'assignmentUi.classify') }}</button>
        </article>
      </div>
    </div>
    <nav v-if="data && data.total > 20" class="assignment-paging" :aria-label="t('assignmentUi.pages')">
      <button class="button" type="button" :disabled="page === 1 || request.pending.value" @click="page--">{{ t('assignmentUi.previous') }}</button>
      <span>{{ page }} / {{ Math.ceil(data.total / 20) }}</span>
      <button class="button" type="button" :disabled="page * 20 >= data.total || request.pending.value" @click="page++">{{ t('assignmentUi.next') }}</button>
    </nav>
    <div v-if="selected" ref="monthsPane" class="assignment-months">
      <header class="assignment-heading"><h3>{{ selected.folder.station_code }} · {{ selected.folder.supplier_name }}</h3>
        <button type="button" class="button" @click="selected = null">{{ t('assignmentUi.close') }}</button></header>
      <SupplierFolder :key="selected.group_id" :cw="folderKey(selected.folder)" @open="emit('open', $event)" />
    </div>
    <form v-if="editing" class="assignment-editor" @submit.prevent="save">
      <h3>{{ editing.folder.station_code }} · {{ editing.folder.supplier_name }}</h3>
      <p>{{ t('assignmentUi.classificationHint') }}</p>
      <label>{{ t('bookingUi.type') }}<select v-model="draftType" :aria-label="t('bookingUi.type')"><option v-for="value in ['hotel', 'transportation', 'unclassified']" :key="value" :value="value">{{ t(`supplier_types.${value}`) }}</option></select></label>
      <template v-if="supervisor">
        <label>{{ t('assignmentUi.owner') }}<select v-model="draftOwner"><option :value="null">{{ t('assignmentUi.unassigned') }}</option>
          <option v-if="draftOwner && !options.data.value?.users.some(u => u.id === draftOwner)" :value="draftOwner">{{ editing.assigned_to?.full_name }}</option>
          <option v-for="user in options.data.value?.users" :key="user.id" :value="user.id">{{ user.full_name }}</option>
        </select></label>
        <label>{{ t('assignmentUi.region') }}<input v-model="draftRegion" maxlength="100" /></label>
        <label>{{ t('assignmentUi.review') }}<textarea v-model="draftReview" maxlength="1000" rows="3" /></label>
      </template>
      <RequestStatus :state="saveRequest.state.value" :error="saveRequest.error.value" />
      <p v-if="saveRequest.error.value?.code === 'VERSION_CONFLICT'">{{ t('assignmentUi.conflict') }}</p>
      <div class="assignment-paging"><button type="submit" class="button primary" :disabled="saveRequest.pending.value">{{ t('assignmentUi.save') }}</button>
        <button type="button" class="button" :disabled="saveRequest.pending.value" @click="editing = null">{{ t('assignmentUi.close') }}</button></div>
    </form>
  </section>
</template>
<style scoped>
.folder-assignments { margin-bottom: 1.25rem; padding: clamp(1rem, 2vw, 1.5rem); }
.assignment-heading { display: flex; align-items: start; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.assignment-heading p { max-width: 75ch; }
.assignment-filters, .assignment-editor { display: flex; gap: .85rem; flex-wrap: wrap; align-items: end; margin-block: 1rem; }
.assignment-filters label, .assignment-editor label { display: grid; gap: .4rem; flex: 1 1 170px; }
.assignment-filters input, .assignment-filters select, .assignment-editor input, .assignment-editor select, .assignment-editor textarea { width: 100%; min-width: 0; border: 1px solid var(--line); border-radius: 8px; padding: .65rem; background: var(--surface); color: var(--ink); }
.assignment-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 290px), 1fr)); gap: .8rem; }
.assignment-section { margin-block: 1.2rem; }
.assignment-section h3 { font-size: .95rem; margin-bottom: .7rem; }
.assignment-card { border: 1px solid var(--line); border-radius: 12px; padding: 1rem; overflow-wrap: anywhere; }
.assignment-open { display: flex; gap: .7rem; width: 100%; border: 0; padding: 0; text-align: start; background: transparent; color: inherit; cursor: pointer; }
.assignment-open > span { display: grid; gap: .4rem; min-width: 0; }
.assignment-open svg { flex-shrink: 0; width: 24px; height: 24px; }
.assignment-card p, .assignment-card details { font-size: .85rem; margin-block: .65rem; }
.assignment-review { color: var(--muted); }
.assignment-card dt { font-weight: 650; }
.assignment-card dd { margin: 0 0 .5rem; }
.assignment-paging { display: flex; align-items: center; gap: .8rem; margin-top: 1rem; }
.assignment-months { scroll-margin-top: 6rem; min-width: 0; }
.assignment-months, .assignment-editor { border-top: 1px solid var(--line); padding-top: 1rem; margin-top: 1rem; }
.assignment-editor h3, .assignment-editor p { flex-basis: 100%; }
.assignment-editor { align-items: start; }
</style>
