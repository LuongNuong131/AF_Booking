<script setup lang="ts">
import { onScopeDispose, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useFoldersStore } from '../stores/folders'
import type { FolderCard as Card } from '../types/api.generated'
import { formatDateTime } from '../utils/dateTime'
import BaseIcon from './BaseIcon.vue'
import StatusTag from './StatusTag.vue'
const props = withDefaults(defineProps<{ folder: Card; selectable?: boolean }>(), {
  selectable: true,
})
defineEmits<{ open: [cw: string] }>()
const { t } = useI18n(),
  auth = useAuthStore(),
  store = useFoldersStore()
let stop: (() => void) | undefined
watch(
  () => props.folder.cw_number,
  (cw) => {
    stop?.()
    stop = store.watchFolder(cw)
  },
  { immediate: true },
)
onScopeDispose(() => stop?.())
</script>
<template>
  <component
    :is="selectable ? 'button' : 'article'"
    :type="selectable ? 'button' : undefined"
    class="folder-card"
    :class="{ selectable }"
    :data-search-result="selectable ? '' : undefined"
    @click="selectable && $emit('open', folder.cw_number)"
  >
    <div class="folder-card-heading">
      <BaseIcon name="folder" />
      <div>
        <strong class="folder-cw">{{ folder.cw_number }}</strong
        ><strong class="folder-supplier">{{ folder.supplier_name }}</strong>
      </div>
    </div>
    <div class="folder-tags">
      <span class="station-tag">{{ folder.station_code }}</span
      ><span class="supplier-type-tag" :class="folder.supplier_type">{{
        t(`supplier_types.${folder.supplier_type}`)
      }}</span
      ><span class="folder-open">{{ t('folderUi.openCount', { count: folder.open_count }) }}</span>
    </div>
    <div class="folder-card-latest">
      <span>{{ t('folderUi.monthCount', { count: folder.booking_count }) }}</span
      ><StatusTag :status="folder.latest?.status ?? null" />
    </div>
    <p v-if="folder.stale_count" class="folder-stale">
      <BaseIcon name="clock" />{{ t('folderUi.staleCount', { count: folder.stale_count }) }}
    </p>
    <p v-if="folder.latest" class="folder-latest-key">
      {{ folder.latest.period_label }} · {{ folder.latest.display_key }}
    </p>
    <time class="folder-activity" :datetime="folder.last_activity_at">{{
      formatDateTime(folder.last_activity_at, auth.timezone)
    }}</time>
  </component>
</template>
