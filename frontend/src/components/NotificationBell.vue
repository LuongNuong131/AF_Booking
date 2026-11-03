<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useNotificationsStore } from '../stores/notifications'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { notificationText } from '../utils/notificationText'
import { formatDateTime } from '../utils/dateTime'
import { errorMessage } from '../api/request-error'
import type { NotificationItem } from '../types/api.generated'
import BaseIcon from './BaseIcon.vue'
import EmptyState from './EmptyState.vue'
import RequestStatus from './RequestStatus.vue'
const { t } = useI18n()
const notifications = useNotificationsStore(),
  auth = useAuthStore(),
  ui = useUiStore()
const router = useRouter()
const dropdown = ref<HTMLDetailsElement | null>(null)
async function open(item: NotificationItem) {
  if (dropdown.value) dropdown.value.open = false
  void notifications.markRead(item.id).then((ok) => {
    if (!ok && notifications.actionError)
      ui.notify(errorMessage(notifications.actionError), 'error')
  })
  await router.push({ name: 'booking', params: { key: item.booking_key } })
}
async function readAll() {
  if (!(await notifications.markAllRead()) && notifications.actionError)
    ui.notify(errorMessage(notifications.actionError), 'error')
}
function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && dropdown.value?.open) {
    event.stopPropagation()
    dropdown.value.open = false
    dropdown.value.querySelector('summary')?.focus()
  }
}
</script>
<template>
  <details ref="dropdown" class="header-menu notifications-menu" @keydown="onKey">
    <summary
      class="icon-button bell-button"
      :aria-label="t('notifications.open')"
      :title="t('notifications.open')"
    >
      <BaseIcon name="bell" /><span v-if="notifications.unread" class="notification-badge">{{
        notifications.unread > 99 ? t('notifications.many') : notifications.unread
      }}</span>
    </summary>
    <section class="menu-popover notifications-popover" :aria-label="t('notifications.title')">
      <div class="notifications-heading">
        <h2>{{ t('notifications.title') }}</h2>
        <button
          type="button"
          class="text-button"
          :disabled="!notifications.unread || notifications.markingAll"
          @click="readAll"
        >
          {{ t('notifications.markAll') }}
        </button>
      </div>
      <p
        v-if="notifications.loading && !notifications.items.length"
        class="notifications-loading"
        role="status"
      >
        {{ t('common.loading') }}
      </p>
      <RequestStatus
        :state="notifications.listRequest.state"
        :error="notifications.listRequest.error"
        @retry="notifications.refresh"
      />
      <ul v-if="notifications.items.length" class="notification-list">
        <li v-for="item in notifications.items" :key="item.id">
          <button type="button" :class="{ unread: !item.read_at }" @click="open(item)">
            <span
              v-if="!item.read_at"
              class="unread-dot"
              :aria-label="t('notifications.unread')"
            /><span class="notification-content"
              ><span>{{ notificationText(item) }}</span
              ><time :datetime="item.created_at">{{
                formatDateTime(item.created_at, auth.timezone)
              }}</time></span
            >
          </button>
        </li>
      </ul>
      <EmptyState
        v-else-if="
          !notifications.loading &&
          notifications.listRequest.state !== 'error' &&
          notifications.listRequest.state !== 'timeout'
        "
        :title="t('notifications.emptyTitle')"
        :description="t('notifications.emptyBody')"
      />
    </section>
  </details>
</template>
