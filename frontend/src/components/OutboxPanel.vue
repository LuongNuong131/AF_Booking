<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useOutboxStore } from '../stores/outbox'
import { useTasksStore } from '../stores/tasks'
import { errorMessage } from '../api/request-error'
const outbox = useOutboxStore(),
  tasks = useTasksStore(),
  router = useRouter(),
  { t } = useI18n()
function review(id: string, key: string) {
  outbox.reviewId = id
  tasks.openBooking(key, true)
  void router.push({ name: 'home' })
}
</script>
<template>
  <p v-if="outbox.storageError" role="alert" class="field-error">{{ t('outboxUi.cannotQueue') }}</p>
  <details v-if="outbox.count" class="outbox-panel">
    <summary>{{ t('unsent', { n: outbox.count }) }}</summary>
    <ul>
      <li v-for="entry in outbox.entries" :key="entry.id">
        <strong>{{ entry.preview.display_key }}</strong> ·
        {{ t(`outboxUi.${entry.state}`) }}
        <p v-if="entry.error">{{ errorMessage(entry.error) }}</p>
        <button
          v-if="entry.state === 'blocked'"
          class="text-button"
          @click="review(entry.id, entry.key)"
        >
          {{ t('outboxUi.review') }}
        </button>
        <button
          v-else
          :disabled="entry.state === 'sending'"
          class="text-button"
          @click="outbox.retry(entry.id)"
        >
          {{ t('request_retry') }}
        </button>
      </li>
    </ul>
  </details>
</template>
