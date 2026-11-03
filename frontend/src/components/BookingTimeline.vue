<script setup lang="ts">
import { toRef } from 'vue'
import { useMeasuredWindow } from '../composables/useMeasuredWindow'
import { useOutboxStore } from '../stores/outbox'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { formatDateTime } from '../utils/dateTime'
import type { Note } from '../types/api.generated'
import type { RequestFailure } from '../api/errors'
import StatusTag from './StatusTag.vue'
import UserAvatar from './UserAvatar.vue'
import RequestStatus from './RequestStatus.vue'
import EmptyState from './EmptyState.vue'
const { t } = useI18n(),
  auth = useAuthStore()
const props = defineProps<{
  notes: Note[]
  cursor?: string | null
  state?: string
  error?: RequestFailure | null
  compact?: boolean
}>()
defineEmits<{ more: [] }>()
const windowed = useMeasuredWindow(toRef(props, 'notes'))
const outbox = useOutboxStore()
const pending = (id: number) => outbox.entries.find((e) => e.note.id === id)
</script>
<template>
  <section class="booking-timeline" :class="{ compact }" :aria-label="t('bookingUi.activity')">
    <div class="section-heading">
      <h2>{{ t('bookingUi.activity') }}</h2>
      <slot name="actions" />
    </div>
    <div
      v-if="notes.length"
      :class="{ 'timeline-virtual': windowed.active.value }"
      @scroll="windowed.scroll"
    >
      <ol class="timeline-list" :style="windowed.padding.value">
        <li
          v-for="{ row: item, index } in windowed.visible.value"
          :ref="(el) => windowed.measure(item.id, el)"
          :key="item.id"
          class="timeline-item"
          :class="{ latest: index === 0, 'outgoing-note': item.id < 0 }"
        >
          <div class="timeline-marker">
            <UserAvatar :name="item.agent.full_name" small />
          </div>
          <article>
            <header class="timeline-header">
              <strong>{{ item.agent.full_name }}</strong
              ><span v-if="index === 0" class="latest-tag">{{ t('bookingUi.latest') }}</span
              ><time :datetime="item.created_at">{{
                formatDateTime(item.created_at, auth.timezone)
              }}</time>
            </header>
            <span v-if="pending(item.id)" class="draft-label"
              >{{ t(`outboxUi.${pending(item.id)!.state}`) }}
              <button
                v-if="pending(item.id)!.state !== 'sending'"
                class="text-button"
                @click="outbox.retry(pending(item.id)!.id)"
              >
                {{ t('request_retry') }}
              </button></span
            >
            <div class="timeline-meta">
              <StatusTag :status="item.status" /><span>{{ item.position }}</span>
            </div>
            <p class="note-content">{{ item.note || t('bookingUi.noNote') }}</p>
            <ul v-if="item.attachments.length" class="attachment-list">
              <li v-for="file in item.attachments" :key="file.id">
                {{ file.file_name }}
              </li>
            </ul>
            <slot name="note-actions" :note="item" />
          </article>
        </li>
      </ol>
    </div>
    <EmptyState v-else :title="t('bookingUi.noActivity')" :description="t('new_booking')" />
    <RequestStatus :state="state || 'idle'" :error="error" @retry="$emit('more')" />
    <button
      v-if="cursor"
      type="button"
      class="button timeline-more"
      :disabled="state === 'loading' || state === 'slow'"
      @click="$emit('more')"
    >
      {{ t(state === 'loading' || state === 'slow' ? 'common.loading' : 'bookingUi.loadMore') }}
    </button>
  </section>
</template>
