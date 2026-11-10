<script setup lang="ts">
import EmptyState from '../../components/EmptyState.vue'
import { reactive, ref, onMounted } from 'vue'
import { ElDialog } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { api } from '../../api/client'
import { useRequest } from '../../composables/useRequest'
import { useViewRefresh } from '../../composables/useViewRefresh'
import { timeouts } from '../../config/timeouts'
import type { AdminStatus } from '../../types/api.generated'
import RequestStatus from '../../components/RequestStatus.vue'
const { t } = useI18n(),
  editing = ref(false),
  isNew = ref(false)
const list = useRequest(
  async ({ signal, timeoutMs }) =>
    (
      await api.get<AdminStatus[]>('/admin/statuses', {
        signal,
        timeout: timeoutMs,
      })
    ).data,
  { timeoutMs: timeouts.list, retry: true },
)
const form = reactive<AdminStatus>({
  id: 0,
  code: '',
  label: '',
  position_label: '',
  note_required: false,
  is_done: false,
  sort_order: 0,
  is_active: true,
  stale_after_hours: null,
  suggest_task: false,
  default_task_days: null,
  invoice_required: false,
})
const mutation = useRequest(
  async ({ signal, timeoutMs }) => {
    const body = { ...form }
    if (isNew.value) {
      const { id: _, ...create } = body
      return (
        await api.post('/admin/statuses', create, {
          signal,
          timeout: timeoutMs,
        })
      ).data
    }
    return (await api.patch('/admin/statuses', body, { signal, timeout: timeoutMs })).data
  },
  { timeoutMs: timeouts.profile },
)
function open(status?: AdminStatus) {
  isNew.value = !status
  Object.assign(
    form,
    status ?? {
      id: 0,
      code: '',
      label: '',
      position_label: '',
      note_required: false,
      is_done: false,
      sort_order: 0,
      is_active: true,
      stale_after_hours: null,
      suggest_task: false,
      default_task_days: null,
      invoice_required: false,
    },
  )
  editing.value = true
  mutation.error.value = null
  mutation.state.value = 'idle'
}
async function save() {
  if (mutation.pending.value) return
  if (await mutation.run()) {
    editing.value = false
    await list.run()
  }
}
function close() {
  if (!mutation.pending.value) editing.value = false
}
onMounted(() => {
  void list.run()
})
useViewRefresh(() => list.run())
</script>
<template>
  <section>
    <header class="admin-section-heading">
      <h2>{{ t('adminUi.statuses') }}</h2>
      <button type="button" class="button primary" @click="open()">
        {{ t('adminUi.createStatus') }}
      </button>
    </header>
    <p class="muted">{{ t('adminUi.statusHint') }}</p>
    <RequestStatus :state="list.state.value" :error="list.error.value" @retry="list.run" />
    <EmptyState v-if="list.state.value === 'success' && !list.data.value?.length" :title="t('common.noRecords')" :description="t('common.noRecordsHint')" />
    <div v-if="list.data.value?.length" class="admin-table-wrap">
      <table class="admin-table">
        <thead>
          <tr>
            <th>{{ t('adminUi.code') }}</th>
            <th>{{ t('adminUi.label') }}</th>
            <th>{{ t('bookingUi.position') }}</th>
            <th>{{ t('adminUi.active') }}</th>
            <th>{{ t('adminUi.flags') }}</th>
            <th>{{ t('adminUi.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="status in list.data.value ?? []" :key="status.id">
            <td>{{ status.code }}</td>
            <td>{{ status.label }}</td>
            <td>{{ status.position_label }}</td>
            <td>
              {{ t(status.is_active ? 'adminUi.enabled' : 'adminUi.disabled') }}
            </td>
            <td>
              {{ status.is_done ? t('status_labels.done') : '' }}
              {{ status.note_required ? t('adminUi.noteRequired') : '' }}
            </td>
            <td>
              <button type="button" class="text-button" @click="open(status)">
                {{ t('adminUi.edit') }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <ElDialog
      :model-value="editing"
      :title="t(isNew ? 'adminUi.createStatus' : 'adminUi.editStatus')"
      width="600px"
      :close-on-click-modal="false"
      :close-on-press-escape="!mutation.pending.value"
      :show-close="!mutation.pending.value"
      @update:model-value="close"
      ><form class="admin-edit-form" @submit.prevent="save">
        <label
          >{{ t('adminUi.code')
          }}<input
            v-model="form.code"
            pattern="[A-Z][A-Z0-9_]{0,39}"
            maxlength="40"
            required /></label
        ><label
          >{{ t('adminUi.label') }}<input v-model="form.label" maxlength="100" required /></label
        ><label
          >{{ t('bookingUi.position')
          }}<input v-model="form.position_label" maxlength="60" required /></label
        ><label
          >{{ t('adminUi.sortOrder')
          }}<input
            v-model.number="form.sort_order"
            type="number"
            min="0"
            max="100000"
            required /></label
        ><label
          >{{ t('adminUi.staleHours')
          }}<input
            :value="form.stale_after_hours ?? ''"
            type="number"
            min="1"
            max="87600"
            @input="
              form.stale_after_hours = ($event.target as HTMLInputElement).value
                ? Number(($event.target as HTMLInputElement).value)
                : null
            " /></label
        ><label
          >{{ t('adminUi.defaultTaskDays')
          }}<input
            :value="form.default_task_days ?? ''"
            type="number"
            min="1"
            max="90"
            @input="
              form.default_task_days = ($event.target as HTMLInputElement).value
                ? Number(($event.target as HTMLInputElement).value)
                : null
            " /></label
        ><label
          v-for="flag in [
            'note_required',
            'is_done',
            'is_active',
            'suggest_task',
            'invoice_required',
          ] as const"
          :key="flag"
          class="preference-toggle"
          ><input v-model="form[flag]" type="checkbox" />{{ t(`adminUi.${flag}`) }}</label
        ><RequestStatus :state="mutation.state.value" :error="mutation.error.value" @retry="save" />
        <div class="admin-form-actions">
          <button class="button primary" type="submit" :disabled="mutation.pending.value">
            {{ t('adminUi.confirm') }}</button
          ><button class="button" type="button" :disabled="mutation.pending.value" @click="close">
            {{ t('common.cancel') }}
          </button>
        </div>
      </form></ElDialog
    >
  </section>
</template>
