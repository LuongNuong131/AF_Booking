<script setup lang="ts">
import { onMounted, onScopeDispose, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { useViewRefresh } from '../composables/useViewRefresh'
import { useCollaborationStore } from '../stores/collaboration'
import { useFoldersStore } from '../stores/folders'
import { timeouts } from '../config/timeouts'
import type { FolderCard as Card, Page } from '../types/api.generated'
import { folderKey } from '../utils/folderKey'
import FolderCard from './FolderCard.vue'
import FolderFollowButton from './FolderFollowButton.vue'
import PageControls from './PageControls.vue'
import RequestStatus from './RequestStatus.vue'
const { t } = useI18n(), router = useRouter(), store = useCollaborationStore()
const page = ref(1)
const request = useRequest(async ({ signal, timeoutMs }) =>
  (await api.get<Page<Card>>('/following/folders', { params: { page: page.value, size: 10 }, signal, timeout: timeoutMs })).data,
  { timeoutMs: timeouts.list, retry: true })
onScopeDispose(useFoldersStore().subscribe((key, card) => {
  if (request.data.value) request.data.value = { ...request.data.value,
    items: request.data.value.items.map(item => folderKey(item) === key ? card : item) }
}))
async function load() {
  const result = await request.run()
  if (result && page.value > 1 && !result.items.length) page.value = Math.max(1, Math.ceil(result.total / 10))
}
onMounted(load)
watch(page, load)
watch(() => store.revision, load)
useViewRefresh(load)
</script>
<template>
  <section class="followed-folders" :aria-label="t('followUi.heading')">
    <p class="muted">{{ t('followUi.hint') }}</p>
    <RequestStatus :state="request.state.value" :error="request.error.value" @retry="load" />
    <article v-for="folder in request.data.value?.items" :key="folderKey(folder)" class="followed-folder">
      <FolderCard :folder="folder" @open="router.push({ name: 'summary-folder', params: { cw: $event } })" />
      <FolderFollowButton :folder-key="folderKey(folder)" :following="true" />
    </article>
    <p v-if="request.state.value === 'success' && !request.data.value?.items.length" class="muted">{{ t('followUi.empty') }}</p>
    <PageControls summary-key="followUi.page" :page="page" :size="10" :total="request.data.value?.total ?? 0" @change="page = $event" />
  </section>
</template>
<style scoped>
.followed-folders { display: grid; gap: .8rem; min-width: 0; }
.followed-folder { display: grid; gap: .4rem; min-width: 0; }
.followed-folder .folder-follow-button { justify-self: start; }
</style>
