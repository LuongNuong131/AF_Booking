<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useFoldersStore } from '../stores/folders'
import { useAuthStore } from '../stores/auth'
import { useRequest } from '../composables/useRequest'
import { useViewRefresh } from '../composables/useViewRefresh'
import { timeouts } from '../config/timeouts'
import { build_key } from '../utils/bookingKey'
import { zonedToday } from '../utils/summaryFilters'
import FolderCard from './FolderCard.vue'
import BookingMonthList from './BookingMonthList.vue'
import SupplierEditor from './SupplierEditor.vue'
import RequestStatus from './RequestStatus.vue'
const props = defineProps<{ cw: string }>(),
  emit = defineEmits<{ open: [key: string] }>()
const { t } = useI18n(),
  store = useFoldersStore(),
  auth = useAuthStore(),
  adding = ref(false),
  month = ref(zonedToday(auth.timezone).slice(0, 7))
const value = computed(() => store.detail(props.cw))
const request = useRequest(
  (ctx, cw: string, force: boolean = false) => store.readDetail(ctx, cw, force),
  { timeoutMs: timeouts.search, retry: true },
)
async function load(force = false) {
  const result = await request.run(props.cw, force)
  if (result) store.remember(props.cw)
}
watch(
  () => props.cw,
  () => {
    adding.value = false
    void load()
  },
  { immediate: true },
)
useViewRefresh(() => load(true))
function newMonth() {
  if (!value.value || !/^20\d{2}-(0[1-9]|1[0-2])$/.test(month.value)) return
  emit(
    'open',
    build_key(props.cw, value.value.folder.station_code, month.value.slice(2).replace('-', '')),
  )
}
</script>
<template>
  <section class="supplier-folder" :aria-label="t('folderUi.folder')">
    <RequestStatus :state="request.state.value" :error="request.error.value" @retry="load(true)" />
    <div
      v-if="request.pending.value && !value"
      class="folder-skeleton"
      role="status"
      :aria-label="t('common.loading')"
    >
      <div v-for="n in 3" :key="n" class="skeleton-line" />
    </div>
    <template v-if="value"
      ><FolderCard :folder="value.folder" :selectable="false" /><SupplierEditor
        :cw="cw"
        :name="value.folder.supplier_name"
        :type="value.folder.supplier_type" />
      <header class="folder-month-heading">
        <h3>{{ t('folderUi.months') }}</h3>
        <button type="button" class="button" @click="adding = !adding">
          {{ t('folderUi.newMonth') }}
        </button>
      </header>
      <form v-if="adding" class="new-month-form" @submit.prevent="newMonth">
        <label
          >{{ t('bookingUi.period')
          }}<input v-model="month" type="month" min="2000-01" max="2099-12" required /></label
        ><button type="submit" class="button primary">{{ t('folderUi.openMonth') }}</button>
      </form>
      <BookingMonthList :months="value.months" @open="emit('open', $event)"
    /></template>
    <p v-if="store.liveError" class="movement-hint">
      {{ t('folderUi.liveError') }}
      <button type="button" class="text-button" @click="load(true)">
        {{ t('bookingUi.refresh') }}
      </button>
    </p>
  </section>
</template>
