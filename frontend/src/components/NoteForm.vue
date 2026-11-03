<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Status } from '../types/api.generated'
import type { RequestFailure } from '../api/errors'
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
function selectStatus(code: string) {
  emit('update:statusCode', code)
  emit('engage')
}
</script>
<template>
  <form class="note-form" :aria-label="t('bookingUi.noteForm')" @submit.prevent="emit('save')">
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
          <span>{{ status.label }}</span
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
        <button type="submit" class="button primary save-note" :disabled="!canSave || pending">
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
