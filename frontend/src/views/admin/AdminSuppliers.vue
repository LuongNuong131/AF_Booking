<script setup lang="ts">
import { ref, onScopeDispose } from 'vue'
import { useFoldersStore } from '../../stores/folders'
import { ElDialog } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { usePagedApi } from '../../composables/usePagedApi'
import { useRequest } from '../../composables/useRequest'
import { api } from '../../api/client'
import { timeouts } from '../../config/timeouts'
import type { FolderCard as Card, StationOption } from '../../types/api.generated'
import FolderCard from '../../components/FolderCard.vue'
import SupplierFolder from '../../components/SupplierFolder.vue'
import StationField from '../../components/StationField.vue'
import PageControls from '../../components/PageControls.vue'
import RequestStatus from '../../components/RequestStatus.vue'
const { t } = useI18n(),
  q = ref(''),
  station = ref(''),
  type = ref(''),
  cw = ref<string | null>(null),
  mode = ref<'suppliers' | 'stations'>('suppliers')
const list = usePagedApi<Card>(
  () => '/folders',
  () => ({
    q: q.value,
    ...(station.value ? { station_code: station.value } : {}),
    ...(type.value ? { supplier_type: type.value } : {}),
  }),
)
const stations = usePagedApi<StationOption>(
  () => '/admin/stations',
  () => ({ q: q.value }),
)
onScopeDispose(
  useFoldersStore().subscribe((cw, card) => {
    const value = list.request.data.value
    if (value)
      list.request.data.value = {
        ...value,
        items: value.items.map((item) =>
          item.cw_number === cw && item.last_activity_at <= card.last_activity_at ? card : item,
        ),
      }
  }),
)
const selected = ref<StationOption | null>(null),
  name = ref('')
const mutation = useRequest(
  async ({ signal, timeoutMs }) =>
    (
      await api.patch(
        `/admin/stations/${selected.value?.code}`,
        { name: name.value.trim() || null },
        { signal, timeout: timeoutMs },
      )
    ).data,
  { timeoutMs: timeouts.profile },
)
function edit(value: StationOption) {
  selected.value = value
  name.value = value.name ?? ''
  mutation.error.value = null
  mutation.state.value = 'idle'
}
async function save() {
  if (mutation.pending.value) return
  if (await mutation.run()) {
    selected.value = null
    await stations.load()
  }
}
function close() {
  if (!mutation.pending.value) selected.value = null
}
async function closeFolder() {
  cw.value = null
  await list.load()
}
</script>
<template>
  <section>
    <h2>{{ t('adminUi.suppliers') }}</h2>
    <div class="summary-mode-nav">
      <button
        v-for="value in ['suppliers', 'stations'] as const"
        :key="value"
        type="button"
        class="button"
        :class="{ selected: mode === value }"
        @click="mode = value"
      >
        {{ t(`adminUi.${value}`) }}
      </button>
    </div>
    <form
      class="admin-filters"
      @submit.prevent="mode === 'suppliers' ? list.apply() : stations.apply()"
    >
      <label>{{ t('adminUi.search') }}<input v-model="q" maxlength="100" /></label
      ><StationField v-if="mode === 'suppliers'" v-model="station" /><label
        v-if="mode === 'suppliers'"
        >{{ t('bookingUi.type')
        }}<select :aria-label="t('bookingUi.type')" v-model="type">
          <option value="">{{ t('bookingUi.allTypes') }}</option>
          <option value="unclassified">{{ t('supplier_types.unclassified') }}</option>
          <option value="hotel">{{ t('supplier_types.hotel') }}</option>
          <option value="transportation">
            {{ t('supplier_types.transportation') }}
          </option>
        </select></label
      ><button class="button" type="submit">{{ t('adminUi.apply') }}</button>
    </form>
    <template v-if="mode === 'suppliers'"
      ><RequestStatus
        :state="list.request.state.value"
        :error="list.request.error.value"
        @retry="list.load" />
      <div class="folder-card-grid summary-folder-grid">
        <FolderCard
          v-for="folder in list.items.value"
          :key="folder.cw_number + folder.station_code"
          :folder="folder"
          @open="cw = $event"
        />
      </div>
      <PageControls
        :page="list.page.value"
        :total="list.total.value"
        :size="20"
        summary-key="folderUi.pageOf"
        @change="list.page.value = $event" /></template
    ><template v-else
      ><RequestStatus
        :state="stations.request.state.value"
        :error="stations.request.error.value"
        @retry="stations.load" />
      <div class="admin-table-wrap">
        <table class="admin-table">
          <thead>
            <tr>
              <th>{{ t('bookingUi.station') }}</th>
              <th>{{ t('adminUi.label') }}</th>
              <th>{{ t('folderUi.folders') }}</th>
              <th>{{ t('adminUi.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="station in stations.items.value" :key="station.code">
              <td>{{ station.code }}</td>
              <td>{{ station.name || '—' }}</td>
              <td>{{ station.folder_count }}</td>
              <td>
                <button type="button" class="text-button" @click="edit(station)">
                  {{ t('adminUi.edit') }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <PageControls
        :page="stations.page.value"
        :total="stations.total.value"
        :size="20"
        summary-key="adminUi.stationPageOf"
        @change="stations.page.value = $event" /></template
    ><ElDialog
      :model-value="!!cw"
      :title="t('folderUi.folder')"
      width="850px"
      @update:model-value="closeFolder"
      ><SupplierFolder
        v-if="cw"
        :cw="cw"
        @open="
          $router.push({
            name: 'booking',
            params: { key: $event },
            query: { from: '/summary?view=folders' },
          })
        " /></ElDialog
    ><ElDialog
      :model-value="!!selected"
      :title="t('adminUi.editStation')"
      width="500px"
      @update:model-value="close"
      ><form class="admin-edit-form" @submit.prevent="save">
        <strong>{{ selected?.code }}</strong
        ><label>{{ t('adminUi.label') }}<input v-model="name" maxlength="100" /></label
        ><RequestStatus
          :state="mutation.state.value"
          :error="mutation.error.value"
          @retry="save"
        /><button class="button primary" type="submit" :disabled="mutation.pending.value">
          {{ t('adminUi.confirm') }}
        </button>
      </form></ElDialog
    >
  </section>
</template>
