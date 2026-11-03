<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useUiStore, type Theme } from '../stores/ui'
import { useRequest } from '../composables/useRequest'
import { api } from '../api/client'
import { parseUser } from '../api/auth-payload'
import { reminderPreferences, type ReminderPreferences } from '../utils/taskDates'
import { validTimeZone } from '../utils/dateTime'
import { timeouts } from '../config/timeouts'
import UserAvatar from '../components/UserAvatar.vue'
import RequestStatus from '../components/RequestStatus.vue'
const { t } = useI18n(),
  auth = useAuthStore(),
  ui = useUiStore()
const prefs = reactive(reminderPreferences(auth.user?.settings)),
  permissionMessage = ref(''),
  validation = ref(''),
  saved = ref(false)
const notificationsSupported = typeof Notification !== 'undefined'
const needsPermission = computed(
  () => prefs.web_notifications && notificationsSupported && Notification.permission !== 'granted',
)
const request = useRequest(
  async ({ signal, timeoutMs }, settings: ReminderPreferences) =>
    parseUser((await api.patch('/profile', { settings }, { signal, timeout: timeoutMs })).data),
  { timeoutMs: timeouts.profile },
)
function updateTheme(event: Event) {
  ui.setTheme((event.target as HTMLSelectElement).value as Theme)
}
async function enableNotifications() {
  permissionMessage.value = ''
  if (!notificationsSupported) {
    prefs.web_notifications = false
    permissionMessage.value = t('taskUi.notificationsUnavailable')
    return
  }
  // Called only by an explicit control gesture, never by mount/reconnect.
  const result = await Notification.requestPermission().catch(
    () => 'denied' as NotificationPermission,
  )
  if (result !== 'granted') {
    prefs.web_notifications = false
    permissionMessage.value = t('taskUi.notificationsDenied')
  }
}
function notificationChanged() {
  if (prefs.web_notifications) void enableNotifications()
}
async function save() {
  validation.value = ''
  saved.value = false
  if (!validTimeZone(prefs.timezone, '')) {
    validation.value = t('taskUi.invalidTimezone')
    return
  }
  const generation = auth.epoch,
    result = await request.run({ ...prefs })
  if (result && generation === auth.epoch) {
    auth.user = result
    saved.value = true
  }
}
</script>
<template>
  <section class="page-shell">
    <div class="page-heading">
      <p class="page-eyebrow">{{ t('app.workspace') }}</p>
      <h1>{{ t('pages.profileTitle') }}</h1>
      <p>{{ t('pages.profileDescription') }}</p>
    </div>
    <div class="profile-card">
      <div class="profile-heading">
        <UserAvatar :name="auth.user?.full_name || ''" />
        <div>
          <h2>{{ auth.user?.full_name }}</h2>
          <p>{{ t(`roles.${auth.user?.role || 'agent'}`) }}</p>
        </div>
      </div>
      <dl class="profile-details">
        <div>
          <dt>{{ t('auth.username') }}</dt>
          <dd>{{ auth.user?.username }}</dd>
        </div>
        <div>
          <dt>{{ t('profile.timezone') }}</dt>
          <dd>{{ auth.timezone }}</dd>
        </div>
      </dl>
      <label class="theme-field"
        ><span>{{ t('theme.title') }}</span
        ><select :value="ui.theme" @change="updateTheme">
          <option v-for="option in ['system', 'light', 'dark']" :key="option" :value="option">
            {{ t(`theme.${option}`) }}
          </option>
        </select></label
      >
      <form
        class="reminder-preferences"
        :aria-label="t('taskUi.preferences')"
        @submit.prevent="save"
      >
        <h2>{{ t('taskUi.preferences') }}</h2>
        <label
          >{{ t('profile.timezone')
          }}<input v-model="prefs.timezone" list="timezones" required maxlength="100" /></label
        ><datalist id="timezones">
          <option
            v-for="zone in [
              'Asia/Ho_Chi_Minh',
              'Europe/Paris',
              'America/Toronto',
              'America/New_York',
              'UTC',
            ]"
            :key="zone"
            :value="zone"
          /></datalist
        ><label
          >{{ t('taskUi.defaultTime')
          }}<input v-model="prefs.default_remind_time" type="time" required /></label
        ><label class="preference-toggle"
          ><input v-model="prefs.skip_weekends" type="checkbox" />{{
            t('taskUi.defaultSkip')
          }}</label
        ><label class="preference-toggle"
          ><input v-model="prefs.task_sound" type="checkbox" />{{ t('taskUi.sound') }}</label
        ><label class="preference-toggle"
          ><input
            v-model="prefs.web_notifications"
            type="checkbox"
            @change="notificationChanged"
          />{{ t('taskUi.webNotifications') }}</label
        ><button
          v-if="needsPermission"
          type="button"
          class="text-button"
          @click="enableNotifications"
        >
          {{ t('taskUi.enableHere') }}
        </button>
        <p v-if="permissionMessage" class="field-error" role="status">{{ permissionMessage }}</p>
        <p v-if="validation" class="field-error" role="alert">{{ validation }}</p>
        <button type="submit" class="button primary" :disabled="request.pending.value">
          {{ t(request.pending.value ? 'taskUi.saving' : 'taskUi.savePreferences') }}
        </button>
        <p v-if="saved" class="task-preferences-saved" role="status">
          {{ t('taskUi.preferencesSaved') }}
        </p>
        <RequestStatus :state="request.state.value" :error="request.error.value" @retry="save" />
      </form>
    </div>
  </section>
</template>
