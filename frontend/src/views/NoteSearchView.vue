<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { useAuthStore } from '../stores/auth'
import { timeouts } from '../config/timeouts'
import { formatDateTime } from '../utils/dateTime'
import { statusLabel } from '../utils/statusLabel'
import { emptyNoteSearchFilters, readNoteSearchQuery, noteSearchKey, noteSearchQuery, noteSearchValidation, type NoteSearchFilters } from '../utils/noteSearchFilters'
import type { NoteSearchPage, NoteSearchHit, AgentSummary, Status, ReportOptions } from '../types/api.generated'
import BaseIcon from '../components/BaseIcon.vue'
import RequestStatus from '../components/RequestStatus.vue'
import PageControls from '../components/PageControls.vue'
import NoteHighlight from '../components/NoteHighlight.vue'
import StatusTag from '../components/StatusTag.vue'
import '../note-search.css'
const route = useRoute(), router = useRouter(), { t, locale } = useI18n(), auth = useAuthStore()
const draft = reactive(readNoteSearchQuery(route.query).filters)
const result = ref<NoteSearchPage | null>(null)
const resultFilters = ref<NoteSearchFilters | null>(null)
const expanded = ref<Record<number, boolean>>({})
const keywordInput = ref<HTMLInputElement | null>(null)
let lastRouteKey: string | undefined
const request = useRequest(async ({ signal, timeoutMs }, filters: NoteSearchFilters, page: number) =>
  (await api.get<NoteSearchPage>('/search/notes', { params: { ...noteSearchQuery(filters), q: filters.q.trim(), page, size: 20 }, signal, timeout: timeoutMs })).data,
{ timeoutMs: timeouts.list })
const catalogs = useRequest(async ({ signal, timeoutMs }) => {
  const [agents, statuses] = await Promise.all([
    api.get<AgentSummary[]>('/users/lookup', { params: { limit: 50 }, signal, timeout: timeoutMs }),
    api.get<Status[]>('/statuses', { signal, timeout: timeoutMs }),
  ])
  return { agents: agents.data, statuses: statuses.data }
}, { timeoutMs: timeouts.list })
const calendar = useRequest(async ({ signal, timeoutMs }) => (await api.get<ReportOptions>('/reports/center/options', { signal, timeout: timeoutMs })).data, { timeoutMs: timeouts.list })
const agentOptions = computed(() => {
  const values = new Map((catalogs.data.value?.agents ?? []).map(user => [String(user.id), user]))
  if (auth.user) values.set(String(auth.user.id), auth.user)
  return [...values.values()]
})
const statuses = computed(() => catalogs.data.value?.statuses ?? [])
const validation = computed(() => noteSearchValidation(draft, calendar.data.value?.today))
const keywordError = computed(() => !!draft.q.length && ['keywordShort', 'keywordLong'].includes(validation.value ?? ''))
const filterError = computed(() => validation.value && !['keywordShort', 'keywordLong'].includes(validation.value) ? validation.value : null)
const filterCount = computed(() => Object.entries(draft).filter(([key, value]) => key !== 'q' && value !== '').length)
const dirty = computed(() => resultFilters.value !== null && noteSearchKey(draft) !== noteSearchKey(resultFilters.value))
const selectedAgentName = computed(() => agentOptions.value.find(user => String(user.id) === resultFilters.value?.agent_id)?.full_name ?? `#${resultFilters.value?.agent_id}`)
const selectedStatusName = computed(() => statusLabel(statuses.value.find(status => status.code === resultFilters.value?.status_code) ?? { code: resultFilters.value?.status_code ?? '', label: resultFilters.value?.status_code ?? '' }))
function dateLabel(value: string) {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`))
}
async function loadApplied() {
  const next = readNoteSearchQuery(route.query)
  if (noteSearchValidation(next.filters, calendar.data.value?.today)) {
    request.cancel(); request.state.value = 'idle'; result.value = null; resultFilters.value = null; return
  }
  const response = await request.run(next.filters, next.page)
  if (response) {
    const lastPage = Math.max(1, Math.ceil(response.total / 20))
    if (next.page > lastPage) { await router.replace({ name: 'note-search', query: noteSearchQuery(next.filters, lastPage) }); return }
    result.value = response; resultFilters.value = { ...next.filters }; expanded.value = {}
  }
}
async function submit() {
  if (validation.value || request.pending.value) return
  const next = noteSearchQuery(draft)
  if (noteSearchKey(readNoteSearchQuery(route.query).filters) === noteSearchKey(draft) && readNoteSearchQuery(route.query).page === 1) await loadApplied()
  else await router.push({ name: 'note-search', query: next })
}
async function changePage(page: number) {
  if (request.pending.value) return
  await router.push({ name: 'note-search', query: noteSearchQuery(readNoteSearchQuery(route.query).filters, page) })
}
async function resetFilters() {
  draft.date_from = draft.date_to = draft.agent_id = draft.status_code = ''
  await submit()
}
async function clearAll() {
  request.cancel(); Object.assign(draft, emptyNoteSearchFilters())
  if (!Object.keys(route.query).length) await loadApplied()
  else await router.push({ name: 'note-search' })
  keywordInput.value?.focus()
}
function preset(days: number) {
  const today = calendar.data.value?.today
  if (!today) return
  const first = new Date(`${today}T00:00:00Z`)
  first.setUTCDate(first.getUTCDate() - days + 1)
  draft.date_from = first.toISOString().slice(0, 10); draft.date_to = today
}
async function example(value: string) { draft.q = value; await submit() }
const longNote = (row: NoteSearchHit) => (row.note?.length ?? 0) > 420 || (row.note?.split('\n').length ?? 0) > 5
watch(() => JSON.stringify(route.query), () => {
  const filters = readNoteSearchQuery(route.query).filters, key = noteSearchKey(filters)
  if (key !== lastRouteKey) Object.assign(draft, filters)
  lastRouteKey = key
  void loadApplied()
}, { immediate: true })
onMounted(() => { void catalogs.run(); void calendar.run() })
</script>
<template>
  <nav class="summary-mode-nav note-search-navigation" :aria-label="t('folderUi.summaryMode')">
    <RouterLink class="button" :to="{ name: 'summary' }">{{ t('folderUi.bookings') }}</RouterLink>
    <RouterLink class="button" :to="{ name: 'summary', query: { view: 'folders' } }">{{ t('folderUi.folders') }}</RouterLink>
    <RouterLink class="button selected" aria-current="page" :to="{ name: 'note-search', query: route.query }"><BaseIcon name="search" />{{ t('opsUi.noteSearch') }}</RouterLink>
  </nav>
  <section class="page-shell note-search-view">
    <header class="note-search-hero">
      <div class="note-search-hero-icon"><BaseIcon name="search" /></div>
      <div><p class="page-eyebrow">{{ t('noteSearchUi.eyebrow') }}</p><h1>{{ t('opsUi.noteSearch') }}</h1><p>{{ t('noteSearchUi.intro') }}</p></div>
    </header>
    <form class="note-search-panel" :aria-label="t('opsUi.noteSearch')" @submit.prevent="submit">
      <label class="field-label" for="notes-keyword">{{ t('opsUi.keyword') }}</label>
      <div class="note-search-keyword-row"><div class="note-search-keyword"><BaseIcon name="search" /><input id="notes-keyword" ref="keywordInput" v-model="draft.q" type="search" required minlength="3" maxlength="100" autofocus :placeholder="t('noteSearchUi.placeholder')" :aria-invalid="keywordError" aria-describedby="notes-keyword-hint" /><button v-if="draft.q" class="icon-button" type="button" :aria-label="t('noteSearchUi.clearKeyword')" @click="draft.q = ''; keywordInput?.focus()"><BaseIcon name="close" /></button></div><button class="button primary note-search-submit" type="submit" :disabled="!!validation || request.pending.value"><BaseIcon name="search" />{{ t('opsUi.search') }}</button></div>
      <div class="note-search-keyword-help"><p id="notes-keyword-hint" :class="{ 'field-error': keywordError }">{{ t(keywordError ? `noteSearchUi.${validation}` : 'noteSearchUi.keywordHint') }}</p><span>{{ draft.q.trim().length }}/100</span></div>
      <div class="note-search-filter-heading"><span><BaseIcon name="filter" />{{ t('noteSearchUi.filters') }}<span v-if="filterCount" class="note-search-filter-count">{{ filterCount }}</span></span><button type="button" class="text-button" :disabled="!filterCount || request.pending.value" @click="resetFilters">{{ t('noteSearchUi.resetFilters') }}</button></div>
      <div class="note-search-filter-grid">
        <label for="notes-date-from">{{ t('bookingUi.dateFrom') }}<input id="notes-date-from" v-model="draft.date_from" type="date" /></label>
        <label for="notes-date-to">{{ t('bookingUi.dateTo') }}<input id="notes-date-to" v-model="draft.date_to" type="date" /></label>
        <label for="notes-agent">{{ t('bookingUi.agent') }}<select id="notes-agent" v-model="draft.agent_id" :aria-label="t('bookingUi.agent')"><option value="">{{ t('bookingUi.allAgents') }}</option><option v-if="draft.agent_id && !agentOptions.some(user => String(user.id) === draft.agent_id)" :value="draft.agent_id">#{{ draft.agent_id }}</option><option v-for="user in agentOptions" :key="user.id" :value="String(user.id)">{{ user.full_name }}</option></select></label>
        <label for="notes-status">{{ t('bookingUi.status') }}<select id="notes-status" v-model="draft.status_code" :aria-label="t('bookingUi.status')"><option value="">{{ t('bookingUi.allStatuses') }}</option><option v-if="draft.status_code && !statuses.some(row => row.code === draft.status_code)" :value="draft.status_code">{{ draft.status_code }}</option><option v-for="row in statuses" :key="row.id" :value="row.code">{{ statusLabel(row) }}</option></select></label>
      </div>
      <div class="note-search-presets"><span>{{ t('noteSearchUi.quickFilters') }}</span><template v-if="calendar.data.value?.today"><button v-for="days in [1, 7, 30]" :key="days" type="button" class="note-search-preset" @click="preset(days)">{{ t(`noteSearchUi.days${days}`) }}</button></template><button v-if="auth.user" type="button" class="note-search-preset" @click="draft.agent_id = String(auth.user.id)"><BaseIcon name="user" />{{ t('noteSearchUi.myNotes') }}</button></div>
      <p class="note-search-range-hint"><BaseIcon name="clock" />{{ t('noteSearchUi.rangeHint') }}<span v-if="calendar.data.value?.timezone">· {{ calendar.data.value.timezone }}</span></p>
      <p v-if="filterError" class="field-error" role="alert">{{ t(`noteSearchUi.${filterError}`) }}</p>
      <RequestStatus :state="catalogs.state.value === 'loading' ? 'idle' : catalogs.state.value" :error="catalogs.error.value" @retry="catalogs.run" />
    </form>
    <RequestStatus :state="request.state.value" :error="request.error.value" @retry="loadApplied" />
    <section v-if="result && resultFilters" class="note-search-results" :aria-busy="request.pending.value" aria-labelledby="notes-results-heading">
      <header class="note-search-results-heading"><div><h2 id="notes-results-heading">{{ t('noteSearchUi.results') }}<span class="note-search-result-count">{{ t('noteSearchUi.bookingCount', { count: result.total }) }}</span></h2><p>{{ t('noteSearchUi.resultHint') }}</p></div><button type="button" class="text-button" @click="clearAll">{{ t('noteSearchUi.clearAll') }}</button></header>
      <div class="note-search-applied"><span class="note-search-applied-query"><BaseIcon name="search" />{{ resultFilters.q }}</span><span><BaseIcon name="clock" />{{ dateLabel(result.date_from) }} – {{ dateLabel(result.date_to) }} · {{ result.timezone }}</span><span v-if="resultFilters.agent_id"><BaseIcon name="user" />{{ selectedAgentName }}</span><span v-if="resultFilters.status_code">{{ selectedStatusName }}</span></div>
      <p v-if="dirty" class="note-search-draft-hint" role="status">{{ t('noteSearchUi.unapplied') }}</p>
      <div v-if="result.items.length" class="note-search-result-list">
        <article v-for="row in result.items" :key="row.note_id" class="note-search-hit">
          <header class="note-hit-header"><div class="note-hit-booking"><span class="note-hit-folder"><BaseIcon name="folder" /></span><div><RouterLink class="note-hit-booking-link" :to="{ name: 'booking', params: { key: row.booking_key } }">{{ row.display_key }}</RouterLink><p class="note-hit-supplier" :title="row.supplier_name">{{ row.supplier_name }}</p></div></div><StatusTag :status="row.status" /></header>
          <div class="note-hit-tags"><span>{{ row.station_code }}</span><span>{{ t(`supplier_types.${row.supplier_type}`) }}</span><span v-if="row.position">{{ row.position }}</span><strong>{{ t('opsUi.matches', { count: row.match_count }) }}</strong></div>
          <div class="note-hit-note"><span class="note-hit-note-label">{{ t('noteSearchUi.latestMatch') }}</span><p class="search-note-text" :class="{ 'note-search-clamped': longNote(row) && !expanded[row.note_id] }"><NoteHighlight :text="row.note ?? ''" :query="resultFilters.q" /></p><button v-if="longNote(row)" type="button" class="text-button note-hit-expand" :aria-expanded="!!expanded[row.note_id]" @click="expanded[row.note_id] = !expanded[row.note_id]">{{ t(expanded[row.note_id] ? 'noteSearchUi.collapse' : 'noteSearchUi.expand') }}</button></div>
          <footer class="note-hit-footer"><div class="note-hit-author"><span class="note-hit-avatar" aria-hidden="true">{{ row.agent.full_name.slice(0, 1).toUpperCase() }}</span><span><strong>{{ row.agent.full_name }}</strong><time :datetime="row.created_at">{{ formatDateTime(row.created_at, auth.timezone) }}</time></span></div><RouterLink class="text-button note-hit-open" :to="{ name: 'booking', params: { key: row.booking_key } }">{{ t('noteSearchUi.openBooking') }}<BaseIcon name="arrow" /></RouterLink></footer>
        </article>
      </div>
      <div v-else class="note-search-empty"><span class="note-search-empty-icon"><BaseIcon name="search" /></span><h3>{{ t('opsUi.noNotes') }}</h3><p>{{ t('noteSearchUi.noResultsHint') }}</p><button type="button" class="button" @click="resetFilters">{{ t('noteSearchUi.resetFilters') }}</button></div>
      <PageControls v-if="result.total && !request.pending.value" :page="result.page" :size="20" :total="result.total" summary-key="opsUi.searchPage" @change="changePage" />
    </section>
    <div v-else-if="request.pending.value" class="note-search-skeleton" aria-hidden="true"><div v-for="item in 3" :key="item" class="note-search-skeleton-card"><span class="skeleton-line short" /><span class="skeleton-line" /><span class="skeleton-line" /></div></div>
    <div v-else-if="request.state.value === 'idle'" class="note-search-empty note-search-welcome"><span class="note-search-empty-icon"><BaseIcon name="search" /></span><h2>{{ t('noteSearchUi.startTitle') }}</h2><p>{{ t('noteSearchUi.startHint') }}</p><div class="note-search-examples"><button v-for="word in ['contract', 'rejection letter', 'gửi email']" :key="word" type="button" @click="example(word)"><BaseIcon name="search" />{{ word }}</button></div></div>
  </section>
</template>
