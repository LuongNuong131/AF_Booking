<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SearchResponse } from '../types/api.generated'
import FolderCard from './FolderCard.vue'
import BookingMonthList from './BookingMonthList.vue'
import PageControls from './PageControls.vue'
const props = defineProps<{ result: SearchResponse }>(),
  emit = defineEmits<{
    folder: [cw: string]
    booking: [key: string]
    page: [page: number]
  }>()
const { t } = useI18n()
const pagination = computed(() =>
  'total' in props.result ? { page: props.result.page, total: props.result.total } : null,
)
</script>
<template>
  <section class="smart-results" :aria-label="t('folderUi.results')">
    <template v-if="result.kind === 'folder'"
      ><FolderCard :folder="result.folder" @open="emit('folder', $event)" /></template
    ><template v-else-if="result.kind === 'folders'"
      ><div class="folder-card-grid">
        <FolderCard
          v-for="folder in result.items"
          :key="folder.cw_number"
          :folder="folder"
          @open="emit('folder', $event)"
        /></div></template
    ><template v-else-if="result.kind === 'station'"
      ><h3 class="station-result-title">
        {{ result.station.code
        }}<span v-if="result.station.name"> · {{ result.station.name }}</span>
      </h3>
      <section v-for="section in result.sections" :key="section.type" class="station-section">
        <h4>{{ t(`supplier_types.${section.type}`) }}</h4>
        <div class="folder-card-grid">
          <FolderCard
            v-for="folder in section.items"
            :key="folder.cw_number"
            :folder="folder"
            @open="emit('folder', $event)"
          />
        </div>
        <p v-if="!section.items.length" class="muted">
          {{ t('folderUi.noTypeFolders') }}
        </p>
      </section></template
    ><template v-else-if="result.kind === 'station_period'"
      ><h3 class="station-result-title">{{ result.station.code }} · {{ result.period_label }}</h3>
      <BookingMonthList :months="result.items" @open="emit('booking', $event)"
    /></template>
    <p v-else-if="result.kind === 'none'" class="smart-empty" role="status">
      {{ t('empty_search') }}
    </p>
    <PageControls
      v-if="pagination && pagination.total > 20"
      :page="pagination.page"
      :total="pagination.total"
      :size="20"
      :summary-key="result.kind === 'station_period' ? 'bookingUi.pageOf' : 'folderUi.pageOf'"
      @change="emit('page', $event)"
    />
  </section>
</template>
