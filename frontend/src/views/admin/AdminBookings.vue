<script setup lang="ts">
import AdminDeleteButton from '../../components/AdminDeleteButton.vue'
import { ref, watch } from 'vue'
import { useBookingRows, patchBooking } from '../../composables/useBookingRows'
import { useBookingsStore } from '../../stores/bookings'
import { ElDialog } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { usePagedApi } from '../../composables/usePagedApi'
import type { BookingItem } from '../../types/api.generated'
import BookingTable from '../../components/BookingTable.vue'
import AdminNoteHistory from '../../components/AdminNoteHistory.vue'
import PageControls from '../../components/PageControls.vue'
import RequestStatus from '../../components/RequestStatus.vue'
const { t } = useI18n(),
  q = ref(''),
  key = ref<string | null>(null),
  list = usePagedApi<BookingItem>(
    () => '/bookings',
    () => ({ q: q.value, sort: 'updated_at_desc' }),
  )
const store = useBookingsStore()
const live = useBookingRows(
  (event) => {
    const data = list.request.data.value,
      row = data?.items.find((r) => r.booking_key === event.booking_key)
    if (!row || row.version >= event.version) return false
    list.request.data.value = {
      ...data!,
      items: data!.items.map((r) =>
        r.booking_key === event.booking_key ? patchBooking(r, event, store.statuses) : r,
      ),
    }
    return true
  },
  (snapshot) => {
    const data = list.request.data.value
    if (data)
      list.request.data.value = {
        ...data,
        items: data.items.map((r) =>
          r.booking_key === snapshot.booking_key && r.version <= snapshot.version ? snapshot : r,
        ),
      }
  },
)
watch(
  () => list.request.data.value,
  () => live.replay(0),
)
</script>
<template>
  <section>
    <header class="admin-section-heading"><h2>{{ t('adminUi.bookings') }}</h2><RouterLink class="button" :to="{ name: 'admin-data', query: { resource: 'bookings' } }">{{ t('dataUi.manageBookings') }}</RouterLink></header>
    <form class="admin-filters" @submit.prevent="list.apply">
      <label
        >{{ t('folderUi.searchLabel')
        }}<input v-model="q" maxlength="100" :placeholder="t('search_placeholder')" /></label
      ><button class="button" type="submit">{{ t('adminUi.apply') }}</button>
    </form>
    <RequestStatus
      :state="list.request.state.value"
      :error="list.request.error.value"
      @retry="list.load"
    /><BookingTable
      :rows="list.items.value"
      :page="list.page.value"
      :total="list.total.value"
      :size="20"
      @page="list.page.value = $event"
      :loading="list.request.pending.value"
      @open="key = $event"
    ><template #actions="{ row }"><AdminDeleteButton resource="bookings" :identifier="row.booking_key" :label="row.display_key" @deleted="list.load" /></template></BookingTable><PageControls
      :page="list.page.value"
      :total="list.total.value"
      :size="20"
      @change="list.page.value = $event"
    /><ElDialog
      :model-value="!!key"
      :title="t('adminUi.history')"
      width="900px"
      @update:model-value="key = null"
      ><AdminNoteHistory v-if="key" :key="key" :booking-key="key"
    /></ElDialog>
  </section>
</template>
