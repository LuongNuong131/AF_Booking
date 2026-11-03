<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { summaryReturn } from '../utils/summaryFilters'
import { useFoldersStore } from '../stores/folders'
import SupplierFolder from '../components/SupplierFolder.vue'
const route = useRoute(),
  router = useRouter(),
  { t } = useI18n(),
  store = useFoldersStore()
const cw = computed(() => String(route.params.cw)),
  folder = computed(() => store.detail(cw.value)?.folder)
function open(key: string) {
  void router.push({
    name: 'booking',
    params: { key },
    query: { from: route.fullPath },
  })
}
</script>
<template>
  <section class="summary-folder-detail">
    <header class="page-heading detail-heading">
      <button
        type="button"
        class="text-button"
        @click="router.push(summaryReturn(route.query.from))"
      >
        {{ t('bookingUi.backToSummary') }}
      </button>
      <nav class="folder-breadcrumbs" :aria-label="t('folderUi.breadcrumb')">
        <RouterLink to="/summary?view=folders">{{ t('folderUi.folders') }}</RouterLink
        ><span aria-hidden="true">›</span
        ><span aria-current="page"
          >{{ cw }}<span v-if="folder"> — {{ folder.supplier_name }}</span></span
        >
      </nav>
      <h1>{{ t('folderUi.folder') }}</h1>
    </header>
    <SupplierFolder :cw="cw" @open="open" />
  </section>
</template>
