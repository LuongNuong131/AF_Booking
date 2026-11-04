<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { useAuthStore } from '../stores/auth'
import { timeouts } from '../config/timeouts'
import { formatDateTime } from '../utils/dateTime'
import type { NoteSearchPage, AgentSummary, Status } from '../types/api.generated'
import RequestStatus from '../components/RequestStatus.vue'
import PageControls from '../components/PageControls.vue'
import NoteHighlight from '../components/NoteHighlight.vue'
import StatusTag from '../components/StatusTag.vue'
const route = useRoute(),
  router = useRouter(),
  { t } = useI18n(),
  auth = useAuthStore()
const query = ref(String(route.query.q ?? '')),
  from = ref(String(route.query.date_from ?? '')),
  to = ref(String(route.query.date_to ?? '')),
  agent = ref(String(route.query.agent_id ?? '')),
  status = ref(String(route.query.status_code ?? '')),
  page = ref(Number(route.query.page) || 1)
const request = useRequest(
  async ({ signal, timeoutMs }, params: Record<string, string | number>) =>
    (await api.get<NoteSearchPage>('/search/notes', { params, signal, timeout: timeoutMs })).data,
  { timeoutMs: timeouts.list },
)
const catalogs = useRequest(
  async ({ signal, timeoutMs }) => {
    const [agents, statuses] = await Promise.all([
      api.get<AgentSummary[]>('/users/lookup', {
        params: { limit: 50 },
        signal,
        timeout: timeoutMs,
      }),
      api.get<Status[]>('/statuses', { signal, timeout: timeoutMs }),
    ])
    return { agents: agents.data, statuses: statuses.data }
  },
  { timeoutMs: timeouts.list },
)
const valid = computed(() => query.value.trim().length >= 3)
const submitted = ref('')
async function load(reset = false) {
  if (!valid.value) return
  if (reset) page.value = 1
  const params = {
    q: query.value.trim(),
    page: page.value,
    size: 20,
    ...(from.value ? { date_from: from.value } : {}),
    ...(to.value ? { date_to: to.value } : {}),
    ...(agent.value ? { agent_id: agent.value } : {}),
    ...(status.value ? { status_code: status.value } : {}),
  }
  await router.replace({ name: 'note-search', query: params })
  const result = await request.run(params)
  if (result) submitted.value = params.q
}
function changePage(value: number) {
  page.value = value
  void load()
}
onMounted(() => {
  void catalogs.run()
  if (valid.value) void load()
})
</script>
<template>
  <section class="page-shell note-search-view">
    <header class="page-heading">
      <p class="page-eyebrow">{{ t('app.workspace') }}</p>
      <h1>{{ t('opsUi.noteSearch') }}</h1>
      <p>{{ t('opsUi.noteSearchHint') }}</p>
    </header>
    <form class="summary-filters" @submit.prevent="load(true)">
      <label
        >{{ t('opsUi.keyword')
        }}<input v-model="query" required minlength="3" maxlength="100" autofocus /></label
      ><label>{{ t('bookingUi.dateFrom') }}<input v-model="from" type="date" /></label
      ><label>{{ t('bookingUi.dateTo') }}<input v-model="to" type="date" /></label
      ><label
        >{{ t('bookingUi.agent')
        }}<select v-model="agent">
          <option value="">{{ t('bookingUi.allAgents') }}</option>
          <option
            v-for="user in catalogs.data.value?.agents ?? []"
            :key="user.id"
            :value="String(user.id)"
          >
            {{ user.full_name }}
          </option>
        </select></label
      ><label
        >{{ t('bookingUi.status')
        }}<select v-model="status">
          <option value="">{{ t('bookingUi.allStatuses') }}</option>
          <option
            v-for="row in catalogs.data.value?.statuses ?? []"
            :key="row.id"
            :value="row.code"
          >
            {{ row.label }}
          </option>
        </select></label
      ><button type="submit" class="button primary" :disabled="!valid || request.pending.value">
        {{ t('opsUi.search') }}
      </button>
    </form>
    <RequestStatus
      :state="request.state.value"
      :error="request.error.value"
      @retry="load()"
    /><template v-if="request.data.value"
      ><p class="muted">
        {{ request.data.value.date_from }} – {{ request.data.value.date_to }} ·
        {{ request.data.value.timezone }}
      </p>
      <article
        v-for="row in request.data.value.items"
        :key="row.booking_key"
        class="note-search-hit admin-panel"
      >
        <RouterLink :to="{ name: 'booking', params: { key: row.booking_key } }">{{
          row.display_key
        }}</RouterLink>
        <p>
          {{ row.supplier_name }} · {{ row.station_code }} ·
          {{ t(`supplier_types.${row.supplier_type}`) }}
        </p>
        <StatusTag :status="row.status" /><small
          >{{ row.agent.full_name }} · {{ formatDateTime(row.created_at, auth.timezone) }} ·
          {{ t('opsUi.matches', { count: row.match_count }) }}</small
        >
        <p class="search-note-text"><NoteHighlight :text="row.note ?? ''" :query="submitted" /></p>
      </article>
      <p v-if="!request.data.value.items.length" class="muted">{{ t('opsUi.noNotes') }}</p>
      <PageControls
        :page="page"
        :size="20"
        :total="request.data.value.total"
        summary-key="opsUi.searchPage"
        @change="changePage"
    /></template>
  </section>
</template>
