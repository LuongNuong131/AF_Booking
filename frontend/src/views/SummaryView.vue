<script setup lang="ts">
import { computed, onMounted, onScopeDispose, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDebounceFn } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useBookingsStore } from '../stores/bookings'
import { useRequest } from '../composables/useRequest'
import { useViewRefresh } from '../composables/useViewRefresh'
import { patchBooking, useBookingRows } from '../composables/useBookingRows'
import {
  emptyFilters,
  readSummaryQuery,
  summaryParams,
  summaryQuery,
  summaryValidation,
  zonedToday,
} from '../utils/summaryFilters'
import { timeouts } from '../config/timeouts'
import type { AgentSummary, BookingItem } from '../types/api.generated'
import BookingTable from '../components/BookingTable.vue'
import PageControls from '../components/PageControls.vue'
import RequestStatus from '../components/RequestStatus.vue'
import BaseIcon from '../components/BaseIcon.vue'
const { t } = useI18n(),
  route = useRoute(),
  router = useRouter(),
  auth = useAuthStore(),
  store = useBookingsStore()
const initial = readSummaryQuery(route.query),
  filters = reactive(initial.filters),
  page = ref(initial.page)
const rows = ref<BookingItem[]>([]),
  total = ref(0),
  refreshing = ref(false)
let routeEpoch = 0,
  disposed = false
const params = computed(() =>
  summaryParams(readSummaryQuery(route.query).filters, page.value, auth.timezone),
)
const validation = computed(() => summaryValidation(filters))
const request = useRequest(
  (ctx, force: boolean = false) => store.list(ctx, '/bookings', params.value, force),
  { timeoutMs: timeouts.list, retry: true },
)
const statusRequest = useRequest((ctx) => store.catalogue(ctx), {
  timeoutMs: timeouts.list,
  retry: true,
})
const agentQuery = ref('')
const agentRequest = useRequest(
  async ({ signal, timeoutMs }, q = '') =>
    (
      await api.get<AgentSummary[]>('/users/lookup', {
        params: { q, limit: 50 },
        signal,
        timeout: timeoutMs,
      })
    ).data,
  { timeoutMs: timeouts.list, retry: true },
)
const agentOptions = computed(() => {
  const entries = new Map((agentRequest.data.value ?? []).map((agent) => [String(agent.id), agent]))
  for (const row of rows.value)
    if (row.last_agent) entries.set(String(row.last_agent.id), row.last_agent)
  if (auth.user)
    entries.set(String(auth.user.id), { id: auth.user.id, full_name: auth.user.full_name })
  return [...entries.values()].sort((a, b) => a.full_name.localeCompare(b.full_name))
})
async function load(force: boolean = false) {
  if (disposed) return
  if (summaryValidation(readSummaryQuery(route.query).filters)) {
    request.cancel()
    return
  }
  const stamp = live.version()
  const result = await request.run(force)
  if (!result || disposed) return
  rows.value = result.items
  total.value = result.total
  live.replay(stamp)
  if (page.value > 1 && !rows.value.length && total.value <= (page.value - 1) * 20)
    await router.replace({
      name: 'summary',
      query: summaryQuery(filters, Math.max(1, Math.ceil(total.value / 20))),
    })
}
async function commitFilters() {
  if (validation.value || (filters.station_code && !/^[A-Z]{3}$/.test(filters.station_code))) return
  await router.replace({ name: 'summary', query: summaryQuery(filters, 1) })
}
const commitDebounced = useDebounceFn((ticket: number) => {
  if (!disposed && ticket === routeEpoch) return commitFilters()
}, timeouts.searchDebounce)
function changed() {
  request.cancel()
  routeEpoch++
  void commitDebounced(routeEpoch)
}
async function clearFilters() {
  routeEpoch++
  request.cancel()
  Object.assign(filters, emptyFilters())
  await commitFilters()
}
async function today() {
  const day = zonedToday(auth.timezone)
  filters.date_from = day
  filters.date_to = day
  changed()
}
async function changePage(value: number) {
  routeEpoch++
  request.cancel()
  await router.push({ name: 'summary', query: summaryQuery(filters, value) })
}
const searchAgents = useDebounceFn(() => {
  if (!disposed) return agentRequest.run(agentQuery.value)
}, timeouts.searchDebounce)
function findAgents() {
  agentRequest.cancel()
  void searchAgents()
}
function matchesDynamic(item: BookingItem) {
  const f = readSummaryQuery(route.query).filters,
    p = params.value
  return (
    (!f.status_code || item.last_status?.code === f.status_code) &&
    (!f.agent_id || item.last_agent?.id === Number(f.agent_id)) &&
    (!f.is_done || item.is_done === (f.is_done === 'true')) &&
    (!f.stale || item.is_stale === (f.stale === 'true')) &&
    (!p.date_from || item.updated_at >= p.date_from) &&
    (!p.date_to || item.updated_at <= p.date_to)
  )
}
const live = useBookingRows(
  (event) => {
    const index = rows.value.findIndex((row) => row.booking_key === event.booking_key)
    if (index < 0 || rows.value[index]!.version >= event.version) return false
    const patched = patchBooking(rows.value[index]!, event, store.statuses)
    if (!matchesDynamic(patched)) {
      rows.value = rows.value.filter((row) => row.booking_key !== event.booking_key)
      total.value = Math.max(0, total.value - 1)
      refreshing.value = true
      return false
    }
    rows.value[index] = patched
    rows.value.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    return true
  },
  (item) => {
    const index = rows.value.findIndex((row) => row.booking_key === item.booking_key)
    if (index < 0 || rows.value[index]!.version > item.version) return
    if (matchesDynamic(item)) {
      rows.value[index] = item
      rows.value.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    } else {
      rows.value = rows.value.filter((row) => row.booking_key !== item.booking_key)
      total.value = Math.max(0, total.value - 1)
      refreshing.value = true
    }
  },
)
watch(
  () => route.query,
  (query) => {
    routeEpoch++
    const next = readSummaryQuery(query)
    Object.assign(filters, next.filters)
    page.value = next.page
    refreshing.value = false
    void load()
  },
)
useViewRefresh(() => load(true))
onScopeDispose(() => {
  disposed = true
  routeEpoch++
})
onMounted(() => {
  void load()
  void statusRequest.run()
  void agentRequest.run()
})
function open(key: string) {
  void router.push({ name: 'booking', params: { key }, query: { from: route.fullPath } })
}
function stationChanged(event: Event) {
  filters.station_code = (event.target as HTMLInputElement).value.toUpperCase().replace(/[^A-Z]/g, '')
  changed()
}
function refreshPage() {
  refreshing.value = false
  void load(true)
}
</script>
<template>
  <section class="summary-view">
    <header class="page-heading summary-heading">
      <div>
        <p class="page-eyebrow">{{ t('bookingUi.summaryEyebrow') }}</p>
        <h1>{{ t('pages.summaryTitle') }}</h1>
        <p>{{ t('bookingUi.summaryIntro') }}</p>
      </div>
      <button type="button" class="button" @click="load(true)">{{ t('bookingUi.refresh') }}</button>
    </header>
    <section class="summary-controls" :aria-label="t('bookingUi.filters')">
      <label class="summary-search"
        ><BaseIcon name="search" /><span class="sr-only">{{ t('bookingUi.searchBookings') }}</span
        ><input
          v-model="filters.q"
          maxlength="100"
          :placeholder="t('search_placeholder')"
          @input="changed"
      /></label>
      <details class="filter-details" open>
        <summary>{{ t('bookingUi.filters') }}</summary>
        <div class="filter-grid">
          <label
            >{{ t('bookingUi.status')
            }}<select
              v-model="filters.status_code"
              :aria-label="t('bookingUi.status')"
              @change="changed"
            >
              <option value="">{{ t('bookingUi.allStatuses') }}</option>
              <option v-for="status in store.statuses" :key="status.id" :value="status.code">
                {{ status.label }}
              </option>
            </select></label
          >
          <label
            >{{ t('bookingUi.agent')
            }}<select
              v-model="filters.agent_id"
              :aria-label="t('bookingUi.agent')"
              @change="changed"
            >
              <option value="">{{ t('bookingUi.allAgents') }}</option>
              <option
                v-if="
                  filters.agent_id && !agentOptions.some((a) => String(a.id) === filters.agent_id)
                "
                :value="filters.agent_id"
              >
                {{ t('bookingUi.agentId', { id: filters.agent_id }) }}
              </option>
              <option v-for="agent in agentOptions" :key="agent.id" :value="String(agent.id)">
                {{ agent.full_name }}
              </option>
            </select></label
          >
          <label
            >{{ t('bookingUi.findAgent')
            }}<input
              v-model="agentQuery"
              maxlength="100"
              :placeholder="t('bookingUi.agentSearchPlaceholder')"
              @input="findAgents"
          /></label>
          <label
            >{{ t('bookingUi.station')
            }}<input
              v-model="filters.station_code"
              :aria-label="t('bookingUi.station')"
              maxlength="3"
              :placeholder="t('station_input_placeholder')"
              @input="stationChanged"
          /></label>
          <label
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
          <label
            >{{ t('bookingUi.period')
            }}<input
              v-model="filters.period"
              :aria-label="t('bookingUi.period')"
              type="month"
              min="2000-01"
              max="2099-12"
              @input="changed"
          /></label>
          <label
            >{{ t('bookingUi.supplier')
            }}<input
              v-model="filters.supplier"
              :aria-label="t('bookingUi.supplier')"
              maxlength="100"
              :placeholder="t('bookingUi.supplierPlaceholder')"
              @input="changed"
          /></label>
          <label
            >{{ t('bookingUi.completion')
            }}<select
              v-model="filters.is_done"
              :aria-label="t('bookingUi.completion')"
              @change="changed"
            >
              <option value="">{{ t('bookingUi.allBookings') }}</option>
              <option value="true">{{ t('status_labels.done') }}</option>
              <option value="false">{{ t('bookingUi.openBookings') }}</option>
            </select></label
          >
          <label
            >{{ t('bookingUi.dateFrom')
            }}<input
              v-model="filters.date_from"
              :aria-label="t('bookingUi.dateFrom')"
              type="date"
              min="2000-01-01"
              max="2099-12-31"
              @input="changed"
          /></label>
          <label
            >{{ t('bookingUi.dateTo')
            }}<input
              v-model="filters.date_to"
              :aria-label="t('bookingUi.dateTo')"
              type="date"
              min="2000-01-01"
              max="2099-12-31"
              @input="changed"
          /></label>
          <label
            >{{ t('bookingUi.stale')
            }}<select v-model="filters.stale" :aria-label="t('bookingUi.stale')" @change="changed">
              <option value="">{{ t('bookingUi.allBookings') }}</option>
              <option value="true">{{ t('bookingUi.staleOnly') }}</option>
              <option value="false">{{ t('bookingUi.recentOnly') }}</option>
            </select></label
          >
          <div class="quick-filters">
            <button type="button" class="button" @click="today">{{ t('bookingUi.today') }}</button
            ><button type="button" class="text-button" @click="clearFilters">
              {{ t('bookingUi.clearFilters') }}
            </button>
          </div>
        </div>
        <p class="filter-timezone">{{ t('bookingUi.datesInZone', { timezone: auth.timezone }) }}</p>
      </details>
      <p v-if="validation" class="field-error" role="alert">{{ t(validation) }}</p>
      <RequestStatus
        :state="statusRequest.state.value"
        :error="statusRequest.error.value"
        @retry="statusRequest.run"
      /><RequestStatus
        :state="agentRequest.state.value"
        :error="agentRequest.error.value"
        @retry="agentRequest.run(agentQuery)"
      />
    </section>
    <div v-if="refreshing" class="booking-update-banner" role="status">
      <span>{{ t('bookingUi.filteredUpdate') }}</span
      ><button
        type="button"
        class="text-button"
        @click="refreshPage"
      >
        {{ t('bookingUi.refresh') }}
      </button>
    </div>
    <RequestStatus
      :state="request.state.value"
      :error="request.error.value"
      @retry="load(true)"
    /><RequestStatus
      :state="live.failedCount.value ? 'error' : live.request.state.value"
      :error="live.error.value || live.request.error.value"
      @retry="live.retry"
    />
    <BookingTable :rows="rows" :loading="request.pending.value" @open="open"
      ><template #footer
        ><PageControls :page="page" :size="20" :total="total" @change="changePage" /></template
    ></BookingTable>
  </section>
</template>
