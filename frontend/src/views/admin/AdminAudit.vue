<script setup lang="ts">
import { reactive, ref } from 'vue'
import { reminderInstant } from '../../utils/taskDates'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../../stores/auth'
import { usePagedApi } from '../../composables/usePagedApi'
import type { AuditEntry } from '../../types/api.generated'
import { formatDateTime } from '../../utils/dateTime'
import PageControls from '../../components/PageControls.vue'
import RequestStatus from '../../components/RequestStatus.vue'
const { t } = useI18n(),
  auth = useAuthStore(),
  filters = reactive({
    user_id: '',
    action: '',
    entity: '',
    date_from: '',
    date_to: '',
  })
const validation = ref('')
const instant = (v: string) => reminderInstant(v.slice(0, 10), v.slice(11, 16), auth.timezone)
function apply() {
  validation.value = ''
  const from = filters.date_from ? instant(filters.date_from) : null,
    to = filters.date_to ? instant(filters.date_to) : null
  if ((filters.date_from && !from) || (filters.date_to && !to) || (from && to && from > to)) {
    validation.value = t('adminUi.invalidDates')
    return
  }
  list.apply()
}
const list = usePagedApi<AuditEntry>(
  () => '/admin/audit',
  () =>
    Object.fromEntries(
      Object.entries(filters)
        .filter(([, v]) => v)
        .map(([k, v]) => [k, k.startsWith('date_') ? instant(v) : v]),
    ),
)
</script>
<template>
  <section>
    <h2>{{ t('adminUi.audit') }}</h2>
    <form class="admin-filters" @submit.prevent="apply">
      <label
        >{{ t('adminUi.userId') }}<input v-model="filters.user_id" type="number" min="1" /></label
      ><label>{{ t('adminUi.action') }}<input v-model="filters.action" maxlength="60" /></label
      ><label
        >{{ t('adminUi.entity')
        }}<select :aria-label="t('adminUi.entity')" v-model="filters.entity">
          <option value="">{{ t('adminUi.all') }}</option>
          <option
            v-for="entity in ['user', 'note', 'booking', 'status', 'station', 'export', 'task']"
            :key="entity"
            :value="entity"
          >
            {{ entity }}
          </option>
        </select></label
      ><label
        >{{ t('bookingUi.dateFrom')
        }}<input v-model="filters.date_from" type="datetime-local" /></label
      ><label
        >{{ t('bookingUi.dateTo') }}<input v-model="filters.date_to" type="datetime-local" /></label
      ><button type="submit" class="button">{{ t('adminUi.apply') }}</button>
    </form>
    <p v-if="validation" class="field-error">{{ validation }}</p>
    <RequestStatus
      :state="list.request.state.value"
      :error="list.request.error.value"
      @retry="list.load"
    />
    <div class="admin-table-wrap">
      <table class="admin-table">
        <thead>
          <tr>
            <th>{{ t('bookingUi.updatedAt') }}</th>
            <th>{{ t('adminUi.fullName') }}</th>
            <th>{{ t('adminUi.action') }}</th>
            <th>{{ t('adminUi.entity') }}</th>
            <th>{{ t('adminUi.details') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in list.items.value" :key="entry.id">
            <td>{{ formatDateTime(entry.created_at, auth.timezone) }}</td>
            <td>{{ entry.user?.full_name || t('adminUi.system') }}</td>
            <td>{{ entry.action }}</td>
            <td>{{ entry.entity_type }} {{ entry.entity_id }}</td>
            <td>
              <details>
                <summary>{{ t('adminUi.details') }}</summary>
                <pre class="audit-meta">{{ JSON.stringify(entry.meta, null, 2) }}</pre>
                <span>{{ entry.ip }}</span>
              </details>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <PageControls
      :page="list.page.value"
      :total="list.total.value"
      :size="20"
      summary-key="adminUi.auditPageOf"
      @change="list.page.value = $event"
    />
  </section>
</template>
