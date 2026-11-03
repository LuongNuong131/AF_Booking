<script setup lang="ts">
import { computed, onScopeDispose, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useFoldersStore } from '../stores/folders'
import { useRequest } from '../composables/useRequest'
import { useViewRefresh } from '../composables/useViewRefresh'
import { readSummaryQuery, summaryQuery } from '../utils/summaryFilters'
import { timeouts } from '../config/timeouts'
import FolderCard from '../components/FolderCard.vue'
import StationField from '../components/StationField.vue'
import PageControls from '../components/PageControls.vue'
import RequestStatus from '../components/RequestStatus.vue'
import BaseIcon from '../components/BaseIcon.vue'
const { t } = useI18n(),
  route = useRoute(),
  router = useRouter(),
  store = useFoldersStore(),
  filters = reactive(readSummaryQuery(route.query).filters)
const page = computed(() => readSummaryQuery(route.query).page)
const params = computed(() => {
  const f = readSummaryQuery(route.query).filters
  return {
    page: page.value,
    size: 20,
    ...(f.q ? { q: f.q } : {}),
    ...(f.station_code ? { station_code: f.station_code } : {}),
    ...(f.supplier_type ? { supplier_type: f.supplier_type } : {}),
  }
})
const result = computed(() => store.page(params.value)),
  cards = computed(() =>
    [...(result.value?.items ?? [])].sort((a, b) =>
      b.last_activity_at.localeCompare(a.last_activity_at),
    ),
  )
const request = useRequest(
  (ctx, force: boolean = false) => store.readPage(ctx, params.value, force),
  { timeoutMs: timeouts.search, retry: true },
)
let timer: ReturnType<typeof setTimeout> | undefined,
  disposed = false
async function load(force = false) {
  const value = await request.run(force)
  if (
    value &&
    !disposed &&
    page.value > 1 &&
    !value.items.length &&
    value.total <= (page.value - 1) * 20
  )
    void changePage(Math.max(1, Math.ceil(value.total / 20)), true)
}
function changed() {
  clearTimeout(timer)
  request.cancel()
  timer = setTimeout(() => {
    if (!disposed && (!filters.station_code || /^[A-Z]{3}$/.test(filters.station_code)))
      void router.replace({
        name: 'summary',
        query: { ...summaryQuery(filters, 1), view: 'folders' },
      })
  }, timeouts.smartSearchDebounce)
}
async function changePage(value: number, replace = false) {
  const target = { name: 'summary', query: { ...summaryQuery(filters, value), view: 'folders' } }
  if (replace) await router.replace(target)
  else await router.push(target)
}
function open(cw: string) {
  void router.push({ name: 'summary-folder', params: { cw }, query: { from: route.fullPath } })
}
watch(
  () => route.query,
  () => {
    clearTimeout(timer)
    Object.assign(filters, readSummaryQuery(route.query).filters)
    void load()
  },
  { immediate: true },
)
useViewRefresh(() => load(true))
onScopeDispose(() => {
  disposed = true
  clearTimeout(timer)
})
</script>
<template>
  <section class="summary-folders">
    <header class="page-heading summary-heading">
      <div>
        <p class="page-eyebrow">{{ t('bookingUi.summaryEyebrow') }}</p>
        <h1>{{ t('pages.summaryTitle') }}</h1>
        <p>{{ t('folderUi.summaryDescription') }}</p>
      </div>
      <button type="button" class="button" @click="load(true)">{{ t('bookingUi.refresh') }}</button>
    </header>
    <section class="summary-controls" :aria-label="t('bookingUi.filters')">
      <label class="summary-search"
        ><BaseIcon name="search" /><span class="sr-only">{{ t('folderUi.findFolders') }}</span
        ><input
          v-model="filters.q"
          maxlength="100"
          :placeholder="t('folderUi.folderPlaceholder')"
          @input="changed"
      /></label>
      <div class="folder-filter-grid">
        <StationField v-model="filters.station_code" @change="changed" /><label
          >{{ t('bookingUi.type')
          }}<select
            v-model="filters.supplier_type"
            :aria-label="t('bookingUi.type')"
            @change="changed"
          >
            <option value="">{{ t('bookingUi.allTypes') }}</option>
            <option value="hotel">{{ t('supplier_types.hotel') }}</option>
            <option value="transportation">{{ t('supplier_types.transportation') }}</option>
          </select></label
        >
      </div>
    </section>
    <RequestStatus :state="request.state.value" :error="request.error.value" @retry="load(true)" />
    <div
      v-if="request.pending.value && !result"
      class="folder-skeleton"
      role="status"
      :aria-label="t('common.loading')"
    >
      <div v-for="n in 6" :key="n" class="skeleton-line" />
    </div>
    <div v-else-if="cards.length" class="folder-card-grid summary-folder-grid">
      <FolderCard v-for="folder in cards" :key="folder.cw_number" :folder="folder" @open="open" />
    </div>
    <p v-else-if="result" class="smart-empty">{{ t('empty_search') }}</p>
    <PageControls
      v-if="result"
      :page="page"
      :total="result.total"
      :size="20"
      summary-key="folderUi.pageOf"
      @change="changePage"
    />
  </section>
</template>
