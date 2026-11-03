<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useBookingsStore } from '../stores/bookings'
import { useAuthStore } from '../stores/auth'
import { useRequest } from '../composables/useRequest'
import { useViewRefresh } from '../composables/useViewRefresh'
import { patchBooking, useBookingRows } from '../composables/useBookingRows'
import { timeouts } from '../config/timeouts'
import { formatDateTime } from '../utils/dateTime'
import type { BookingItem } from '../types/api.generated'
import StatusTag from './StatusTag.vue'
import RequestStatus from './RequestStatus.vue'
import PageControls from './PageControls.vue'
import EmptyState from './EmptyState.vue'
import BaseIcon from './BaseIcon.vue'
const emit = defineEmits<{ open: [key: string] }>()
const { t } = useI18n(),
  store = useBookingsStore(),
  auth = useAuthStore()
const rows = ref<BookingItem[]>([]),
  page = ref(1),
  staleOnly = ref(false),
  mineTotal = ref(0),
  staleTotal = ref(0),
  movement = ref('')
const newKeys = ref(new Set<string>())
let disposed = false
const total = computed(() => (staleOnly.value ? staleTotal.value : mineTotal.value))
const request = useRequest(
  (ctx, force: boolean = false) =>
    staleOnly.value
      ? store.list(ctx, '/bookings/stale', { scope: 'mine', page: page.value, size: 10 }, force)
      : store.list(ctx, '/bookings/mine', { page: page.value, size: 10 }, force),
  { timeoutMs: timeouts.list, retry: true },
)
const countsRequest = useRequest(
  async (ctx, force: boolean = false, includeMine: boolean = false) => {
    const [stale, mine] = await Promise.all([
      store.list(ctx, '/bookings/stale', { scope: 'mine', page: 1, size: 1 }, force),
      includeMine ? store.list(ctx, '/bookings/mine', { page: 1, size: 1 }, force) : undefined,
    ])
    return { stale: stale.total, mine: mine?.total }
  },
  { timeoutMs: timeouts.list, retry: true },
)
async function counts(force: boolean = false, includeMine: boolean = false) {
  if (disposed) return
  const result = await countsRequest.run(force, includeMine)
  if (result && !disposed) {
    staleTotal.value = result.stale
    if (result.mine !== undefined) mineTotal.value = result.mine
  }
}
async function load(force: boolean = false) {
  if (disposed) return
  const stamp = live.version()
  const result = await request.run(force)
  if (!result || disposed) return
  rows.value = result.items
  if (staleOnly.value) staleTotal.value = result.total
  else mineTotal.value = result.total
  newKeys.value = new Set()
  live.replay(stamp)
  if (page.value > 1 && !result.items.length && result.total <= (page.value - 1) * 10) {
    page.value = Math.max(1, Math.ceil(result.total / 10))
    await load(true)
  }
}
async function changePage(value: number) {
  page.value = value
  await load()
}
async function toggleStale() {
  request.cancel()
  staleOnly.value = !staleOnly.value
  page.value = 1
  await load()
}
async function showNew() {
  page.value = 1
  await load(true)
  await counts(true)
}
let countTimer: ReturnType<typeof setTimeout> | undefined
const live = useBookingRows(
  (event) => {
    clearTimeout(countTimer)
    countTimer = setTimeout(() => {
      void counts(true, true)
    }, timeouts.searchDebounce)
    const index = rows.value.findIndex((row) => row.booking_key === event.booking_key)
    if (index >= 0 && rows.value[index]!.version >= event.version) return false
    if (event.last_agent_id !== auth.user?.id) {
      if (index >= 0) {
        rows.value = rows.value.filter((row) => row.booking_key !== event.booking_key)
        movement.value = t('bookingUi.moved', { user: event.last_agent_name })
        if (staleOnly.value) staleTotal.value = Math.max(0, staleTotal.value - 1)
        else mineTotal.value = Math.max(0, mineTotal.value - 1)
      }
      return false
    }
    if (staleOnly.value) {
      if (index >= 0) rows.value[index] = patchBooking(rows.value[index]!, event, store.statuses)
      return index >= 0 || page.value === 1
    }
    if (page.value !== 1) {
      const keys = new Set(newKeys.value)
      keys.add(event.booking_key)
      newKeys.value = keys
      return false
    }
    if (index >= 0) rows.value[index] = patchBooking(rows.value[index]!, event, store.statuses)
    return true
  },
  (item) => {
    const existing = rows.value.find((row) => row.booking_key === item.booking_key)
    if (existing && existing.version > item.version) return
    if (item.last_agent?.id !== auth.user?.id || (staleOnly.value && !item.is_stale)) {
      rows.value = rows.value.filter((row) => row.booking_key !== item.booking_key)
      return
    }
    if (page.value !== 1) {
      const index = rows.value.findIndex((row) => row.booking_key === item.booking_key)
      if (staleOnly.value && index >= 0 && rows.value[index]!.version <= item.version)
        rows.value[index] = item
      return
    }
    const old = rows.value.find((row) => row.booking_key === item.booking_key)
    if (old && old.version > item.version) return
    rows.value = [item, ...rows.value.filter((row) => row.booking_key !== item.booking_key)]
      .sort(
        (a, b) =>
          b.updated_at.localeCompare(a.updated_at) || b.booking_key.localeCompare(a.booking_key),
      )
      .slice(0, 10)
  },
)
useViewRefresh(() => {
  void load(true)
  void counts(true, true)
})
onMounted(() => {
  void load()
  void counts()
})
onScopeDispose(() => {
  disposed = true
  clearTimeout(countTimer)
})
function refreshList() {
  movement.value = ''
  void load(true)
  void counts(true, true)
}
</script>
<template>
  <section class="my-bookings-card" :aria-label="t('bookingUi.myBookings')">
    <header class="mine-header">
      <div class="mine-tabs">
        <button
          type="button"
          class="mine-tab"
          :aria-pressed="!staleOnly"
          @click="staleOnly ? toggleStale() : undefined"
        >
          {{ t('bookingUi.myBookings') }}<span>{{ mineTotal }}</span></button
        ><slot name="tabs" />
      </div>
      <button
        type="button"
        class="stale-chip"
        :class="{ active: staleOnly }"
        :aria-pressed="staleOnly"
        @click="toggleStale"
      >
        <BaseIcon name="clock" />{{ t('bookingUi.staleCount', { count: staleTotal }) }}
      </button>
    </header>
    <div class="mine-list-body">
      <p class="mine-description">{{ t('bookingUi.mineDescription') }}</p>
      <button v-if="newKeys.size" type="button" class="new-items-banner" @click="showNew">
        {{ t('bookingUi.newItems', { count: newKeys.size }) }}
      </button>
      <p v-if="movement" class="movement-hint" role="status">
        {{ movement }}
        <button
          type="button"
          class="text-button"
          @click="refreshList"
        >
          {{ t('bookingUi.refresh') }}
        </button>
      </p>
      <RequestStatus
        :state="request.state.value"
        :error="request.error.value"
        @retry="load(true)"
      /><RequestStatus
        :state="countsRequest.state.value"
        :error="countsRequest.error.value"
        @retry="counts(true, true)"
      /><RequestStatus
        :state="live.failedCount.value ? 'error' : live.request.state.value"
        :error="live.error.value || live.request.error.value"
        @retry="live.retry"
      />
      <div
        v-if="request.pending.value && !rows.length"
        class="mine-skeleton"
        role="status"
        :aria-label="t('common.loading')"
      >
        <div v-for="n in 4" :key="n" class="skeleton-line" />
      </div>
      <TransitionGroup v-else-if="rows.length" name="booking-row" tag="ul" class="mine-list"
        ><li v-for="row in rows" :key="row.booking_key">
          <button type="button" class="mine-booking" @click="emit('open', row.booking_key)">
            <div class="mine-row-heading">
              <strong>{{ row.display_key }}</strong
              ><StatusTag :status="row.last_status" />
            </div>
            <p class="mine-supplier">
              {{ row.supplier.name }}<span>{{ row.station_code }}</span>
            </p>
            <p class="mine-position">{{ row.last_position }}</p>
            <p class="mine-note">{{ row.last_note_preview || t('bookingUi.noNote') }}</p>
            <div class="mine-row-footer">
              <time :datetime="row.updated_at">{{
                formatDateTime(row.updated_at, auth.timezone)
              }}</time
              ><span v-if="row.is_stale" class="stale-age"
                ><BaseIcon name="clock" />{{
                  t('bookingUi.staleHours', {
                    hours: Math.max(
                      0,
                      Math.floor(
                        row.stale_hours ?? (Date.now() - Date.parse(row.updated_at)) / 3600000,
                      ),
                    ),
                  })
                }}</span
              >
            </div>
          </button>
        </li></TransitionGroup
      >
      <EmptyState
        v-else
        :title="t(staleOnly ? 'bookingUi.noStale' : 'bookingUi.emptyMine')"
        :description="t(staleOnly ? 'bookingUi.noStaleBody' : 'bookingUi.emptyMineBody')"
      />
      <PageControls :page="page" :total="total" :size="10" @change="changePage" />
    </div>
  </section>
</template>
