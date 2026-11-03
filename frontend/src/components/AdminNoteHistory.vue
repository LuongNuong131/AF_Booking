<script setup lang="ts">
import { ref, onScopeDispose } from 'vue'
import { useBookingsStore } from '../stores/bookings'
import { ElDialog } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { usePagedApi } from '../composables/usePagedApi'
import { useRequest } from '../composables/useRequest'
import { api } from '../api/client'
import { timeouts } from '../config/timeouts'
import { formatDateTime } from '../utils/dateTime'
import type { AdminNote } from '../types/api.generated'
import PageControls from './PageControls.vue'
import RequestStatus from './RequestStatus.vue'
import StatusTag from './StatusTag.vue'
const props = defineProps<{
    bookingKey?: string
    trash?: boolean
    q?: string
  }>(),
  { t } = useI18n(),
  auth = useAuthStore()
const list = usePagedApi<AdminNote>(
  () => (props.trash ? '/admin/trash' : `/admin/bookings/${props.bookingKey}/notes`),
  () => ({ q: props.q || '' }),
)
const selected = ref<AdminNote | null>(null),
  reason = ref('')
const mutation = useRequest(
  async ({ signal, timeoutMs }) => {
    const note = selected.value!
    if (note.deleted_at)
      return (await api.post(`/admin/notes/${note.id}/restore`, {}, { signal, timeout: timeoutMs }))
        .data
    return (
      await api.delete(`/admin/notes/${note.id}`, {
        data: { reason: reason.value },
        signal,
        timeout: timeoutMs,
      })
    ).data
  },
  { timeoutMs: timeouts.noteSave },
)
function choose(note: AdminNote) {
  selected.value = note
  reason.value = ''
  mutation.error.value = null
  mutation.state.value = 'idle'
}
async function submit() {
  if (mutation.pending.value) return
  const result = await mutation.run()
  if (result) {
    selected.value = null
    await list.load()
  }
}
function close() {
  if (!mutation.pending.value) selected.value = null
}
defineExpose({ reload: list.apply })
onScopeDispose(
  useBookingsStore().subscribe((event) => {
    if (event.booking_key === props.bookingKey || (props.trash && event.snapshot_rebuilt))
      void list.load()
  }),
)
</script>
<template>
  <section class="admin-note-history">
    <RequestStatus
      :state="list.request.state.value"
      :error="list.request.error.value"
      @retry="list.load"
    />
    <article
      v-for="note in list.items.value"
      :key="note.id"
      class="admin-note"
      :class="{ deleted: note.deleted_at }"
    >
      <header>
        <strong>{{ note.display_key }}</strong
        ><StatusTag :status="note.status" /><span>{{ note.agent.full_name }}</span>
      </header>
      <p class="admin-note-body">{{ note.note || t('bookingUi.noNote') }}</p>
      <small>{{ note.position }} · {{ formatDateTime(note.created_at, auth.timezone) }}</small>
      <p v-if="note.deleted_at" class="booking-warning">
        {{
          t('adminUi.deletedBy', {
            user: note.deleted_by?.full_name || t('common.someone'),
            date: formatDateTime(note.deleted_at, auth.timezone),
          })
        }}<br />{{ note.delete_reason }}
      </p>
      <button type="button" class="text-button" @click="choose(note)">
        {{ t(note.deleted_at ? 'adminUi.restore' : 'adminUi.deleteNote') }}
      </button>
    </article>
    <p v-if="!list.items.value.length && !list.request.pending.value" class="muted">
      {{ t('adminUi.noNotes') }}
    </p>
    <PageControls
      :page="list.page.value"
      :total="list.total.value"
      :size="20"
      summary-key="adminUi.notePageOf"
      @change="list.page.value = $event"
    /><ElDialog
      :model-value="!!selected"
      :title="t(selected?.deleted_at ? 'adminUi.restore' : 'adminUi.deleteNote')"
      width="520px"
      :close-on-click-modal="false"
      :close-on-press-escape="!mutation.pending.value"
      :show-close="!mutation.pending.value"
      @update:model-value="close"
      ><form class="admin-edit-form" @submit.prevent="submit">
        <p>{{ selected?.display_key }}</p>
        <p>{{ t('adminUi.rebuildWarning') }}</p>
        <label v-if="!selected?.deleted_at"
          >{{ t('adminUi.reason')
          }}<textarea v-model="reason" minlength="3" maxlength="255" required /></label
        ><RequestStatus
          :state="mutation.state.value"
          :error="mutation.error.value"
          @retry="submit"
        />
        <div class="admin-form-actions">
          <button
            class="button primary"
            type="submit"
            :disabled="
              mutation.pending.value || (!selected?.deleted_at && reason.trim().length < 3)
            "
          >
            {{ t('adminUi.confirm') }}</button
          ><button class="button" type="button" :disabled="mutation.pending.value" @click="close">
            {{ t('common.cancel') }}
          </button>
        </div>
      </form></ElDialog
    >
  </section>
</template>
