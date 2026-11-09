<script setup lang="ts">
import { statusLabel } from '../utils/statusLabel'
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { NoteSnippet, Status } from '../types/api.generated'
import type { RequestFailure } from '../api/errors'
import { api } from '../api/client'
import { useShortcuts } from '../composables/useShortcuts'
import RequestStatus from './RequestStatus.vue'
const { t } = useI18n()
const props = defineProps<{
  statusCode: string
  note: string
  statuses: Status[]
  pending: boolean
  canSave: boolean
  online: boolean
  state: string
  error?: RequestFailure | null
  hasDraft: boolean
  restored?: boolean
  draftFailed?: boolean
  draftPending?: boolean
}>()
const emit = defineEmits<{
  'update:statusCode': [value: string]
  'update:note': [value: string]
  save: []
  discard: []
  engage: []
}>()
const sorted = computed(() =>
  [...props.statuses].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id),
)
const selected = computed(() => props.statuses.find((s) => s.code === props.statusCode))
const noteInvalid = computed(() => !!selected.value?.note_required && !props.note.trim())
const snippets = ref<NoteSnippet[]>([])
const snippetsOpen = ref(false)
const snippetQuery = ref('')
const snippetTitle = ref('')
const snippetsBusy = ref(false)
const snippetsError = ref(false)
async function loadSnippets() {
  snippetsBusy.value = true
  snippetsError.value = false
  try {
    snippets.value = (
      await api.get<NoteSnippet[]>('/snippets', {
        params: { q: snippetQuery.value.trim() || undefined, limit: 30 },
      })
    ).data
  } catch {
    snippetsError.value = true
  } finally {
    snippetsBusy.value = false
  }
}
function toggleSnippets() {
  snippetsOpen.value = !snippetsOpen.value
  if (snippetsOpen.value) void loadSnippets()
}
function applySnippet(item: NoteSnippet) {
  emit('update:note', `${props.note.trimEnd()}${props.note.trim() ? '\n' : ''}${item.text}`)
  snippetsOpen.value = false
  void api.post(`/snippets/${item.id}/use`).catch(() => undefined)
}
async function saveSnippet() {
  const title = snippetTitle.value.trim()
  const text = props.note.trim()
  if (!title || !text) return
  snippetsBusy.value = true
  try {
    await api.post<NoteSnippet>('/snippets', { title, text })
    snippetTitle.value = ''
    await loadSnippets()
  } finally {
    snippetsBusy.value = false
  }
}
async function deleteSnippet(item: NoteSnippet) {
  if (!window.confirm(`${t('bookingUi.snippetDelete')}?`)) return
  await api.delete(`/snippets/${item.id}`)
  snippets.value = snippets.value.filter((entry) => entry.id !== item.id)
}
useShortcuts('note-snippets', [{ key: 'mod+j', allowInput: true, run: toggleSnippets }])
let submitting = false
function submit() {
  if (submitting || props.pending || !props.canSave || noteInvalid.value) return
  submitting = true
  emit('save')
  void nextTick(() => {
    submitting = false
  })
}
function selectStatus(code: string) {
  emit('update:statusCode', code)
  emit('engage')
}
</script>
<template>
  <form class="note-form" :aria-label="t('bookingUi.noteForm')" @submit.prevent="submit">
    <div class="section-heading">
      <h2>{{ t('bookingUi.addUpdate') }}</h2>
      <span v-if="draftPending" class="draft-label">{{ t('bookingUi.savingDraft') }}</span
      ><span v-else-if="restored" class="draft-label">{{ t('bookingUi.draftRestored') }}</span
      ><span v-else-if="hasDraft && !draftFailed" class="draft-label">{{
        t('bookingUi.draft')
      }}</span>
    </div>
    <fieldset class="status-fieldset">
      <legend>{{ t('bookingUi.status') }}</legend>
      <div class="status-options">
        <button
          v-for="(status, index) in sorted"
          :key="status.id"
          type="button"
          :aria-pressed="statusCode === status.code"
          :class="{ selected: statusCode === status.code }"
          @click="selectStatus(status.code)"
        >
          <span>{{ statusLabel(status) }}</span
          ><kbd v-if="index < 5" aria-hidden="true">{{ index + 1 }}</kbd>
        </button>
      </div>
    </fieldset>
    <p v-if="selected" class="position-readonly">
      <span>{{ t('bookingUi.position') }}</span
      ><strong>{{ selected.position_label }}</strong>
    </p>
    <label class="field-label" for="booking-note"
      >{{ t('bookingUi.note')
      }}<span v-if="selected?.note_required" class="required-marker">{{
        t('bookingUi.required')
      }}</span></label
    >
    <div class="snippet-toolbar">
      <button type="button" class="text-button" @click="toggleSnippets">
        {{ t('bookingUi.snippets') }} <kbd>{{ t('bookingUi.snippetsShortcut') }}</kbd>
      </button>
      <div v-if="snippetsOpen" class="snippet-panel">
        <input
          v-model="snippetQuery"
          type="search"
          :placeholder="t('bookingUi.snippetSearch')"
          @input="loadSnippets"
        />
        <div v-if="snippetsBusy" class="muted">{{ t('request_slow') }}</div>
        <div v-else-if="snippetsError" class="field-error">{{ t('request_retry') }}</div>
        <div v-else-if="!snippets.length" class="muted">{{ t('bookingUi.snippetEmpty') }}</div>
        <ul v-else class="snippet-list">
          <li v-for="item in snippets" :key="item.id">
            <button type="button" class="snippet-item" @click="applySnippet(item)">
              <strong>{{ item.title }}</strong><span>{{ item.text }}</span>
            </button>
            <button
              type="button"
              class="icon-button"
              :aria-label="t('bookingUi.snippetDelete')"
              @click="deleteSnippet(item)"
            >×</button>
          </li>
        </ul>
        <div class="snippet-save-row">
          <input v-model="snippetTitle" maxlength="80" :placeholder="t('bookingUi.snippetTitle')" />
          <button type="button" class="button" :disabled="snippetsBusy || !snippetTitle.trim() || !note.trim()" @click="saveSnippet">
            {{ t('bookingUi.snippetSave') }}
          </button>
        </div>
      </div>
    </div>
    <textarea
      id="booking-note"
      :aria-label="t('bookingUi.note')"
      :aria-required="selected?.note_required"
      :value="note"
      maxlength="5000"
      rows="4"
      :placeholder="t('bookingUi.notePlaceholder')"
      :aria-invalid="noteInvalid"
      :aria-describedby="noteInvalid ? 'note-required' : undefined"
      @input="emit('update:note', ($event.target as HTMLTextAreaElement).value)"
      @focus="emit('engage')"
    />
    <p v-if="noteInvalid" id="note-required" class="field-error" role="status">
      {{ t('errors.NOTE_REQUIRED') }}
    </p>
    <p v-if="draftFailed" class="field-error" role="alert">
      {{ t('bookingUi.draftFailed') }}
    </p>
    <slot name="fields" />
    <p v-if="!online" class="booking-warning offline-save" role="status">
      {{ t('network_offline') }}
    </p>
    <div class="note-actions">
      <div class="note-primary-actions">
        <button
          type="submit"
          class="button primary save-note"
          :disabled="!canSave || pending || noteInvalid"
        >
          <span v-if="pending" class="button-spinner" aria-hidden="true" />{{
            t(pending ? 'bookingUi.saving' : 'bookingUi.save')
          }}<kbd v-if="!pending">{{ t('bookingUi.saveShortcut') }}</kbd></button
        ><slot name="task-action" />
      </div>
      <button
        v-if="hasDraft || statusCode || note"
        type="button"
        class="text-button discard-draft"
        @click="emit('discard')"
      >
        {{ t('bookingUi.discardDraft') }}
      </button>
    </div>
    <RequestStatus :state="state" :error="error" @retry="emit('save')" />
  </form>
</template>
