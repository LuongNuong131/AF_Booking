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
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import type { ProfileStats } from '../types/api.generated'
import { formatDateTime } from '../utils/dateTime'
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
const router = useRouter(),
  fullName = ref(auth.user?.full_name ?? ''),
  nameSaved = ref(false)
const oldPassword = ref(''),
  newPassword = ref(''),
  confirmPassword = ref(''),
  passwordValidation = ref('')
const stats = useRequest(
  async ({ signal, timeoutMs }) =>
    (
      await api.get<ProfileStats>('/profile/stats', {
        signal,
        timeout: timeoutMs,
      })
    ).data,
  { timeoutMs: timeouts.profile, retry: true },
)
const nameRequest = useRequest(
  async ({ signal, timeoutMs }) =>
    parseUser(
      (
        await api.patch(
          '/profile',
          { full_name: fullName.value.trim() },
          { signal, timeout: timeoutMs },
        )
      ).data,
    ),
  { timeoutMs: timeouts.profile },
)
const passwordRequest = useRequest(
  async ({ signal, timeoutMs }) =>
    (
      await api.post(
        '/auth/change-password',
        { old_password: oldPassword.value, new_password: newPassword.value },
        { signal, timeout: timeoutMs },
      )
    ).data,
  { timeoutMs: timeouts.profile },
)
async function saveName() {
  nameSaved.value = false
  if (nameRequest.pending.value) return
  const generation = auth.epoch,
    result = await nameRequest.run()
  if (result && generation === auth.epoch) {
    auth.user = result
    nameSaved.value = true
  }
}
async function changePassword() {
  passwordValidation.value = ''
  if (newPassword.value !== confirmPassword.value) {
    passwordValidation.value = t('adminUi.passwordMismatch')
    return
  }
  if (passwordRequest.pending.value) return
  const result = await passwordRequest.run()
  if (result) {
    oldPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    auth.expire()
    await router.replace({ name: 'login' })
  }
}
onMounted(() => {
  void stats.run()
})
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
    void stats.run()
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
      <form class="admin-edit-form profile-name-form" @submit.prevent="saveName">
        <label
          >{{ t('adminUi.fullName')
          }}<input v-model="fullName" minlength="2" maxlength="100" required /></label
        ><button class="button primary" type="submit" :disabled="nameRequest.pending.value">
          {{ t('adminUi.saveName') }}
        </button>
        <p v-if="nameSaved" class="task-preferences-saved">
          {{ t('adminUi.nameSaved') }}
        </p>
        <RequestStatus
          :state="nameRequest.state.value"
          :error="nameRequest.error.value"
          @retry="saveName"
        />
      </form>
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
        <p v-if="permissionMessage" class="field-error" role="status">
          {{ permissionMessage }}
        </p>
        <p v-if="validation" class="field-error" role="alert">
          {{ validation }}
        </p>
        <button type="submit" class="button primary" :disabled="request.pending.value">
          {{ t(request.pending.value ? 'taskUi.saving' : 'taskUi.savePreferences') }}
        </button>
        <p v-if="saved" class="task-preferences-saved" role="status">
          {{ t('taskUi.preferencesSaved') }}
        </p>
        <RequestStatus :state="request.state.value" :error="request.error.value" @retry="save" />
      </form>
      <section class="profile-statistics">
        <h2>{{ t('adminUi.myActivity') }}</h2>
        <RequestStatus
          :state="stats.state.value"
          :error="stats.error.value"
          @retry="stats.run"
        /><template v-if="stats.data.value"
          ><p>
            {{
              t('adminUi.personalCounts', {
                today: stats.data.value.notes_today,
                week: stats.data.value.notes_week,
              })
            }}
            · {{ stats.data.value.timezone }}
          </p>
          <h3>{{ t('adminUi.recentLogins') }}</h3>
          <ul>
            <li v-for="(entry, index) in stats.data.value.login_history" :key="index">
              {{ formatDateTime(entry.created_at, auth.timezone) }} · {{ entry.action }} ·
              {{ entry.ip || '—' }}
            </li>
          </ul></template
        >
      </section>
      <form class="admin-edit-form profile-password-form" @submit.prevent="changePassword">
        <h2>{{ t('adminUi.changePassword') }}</h2>
        <p class="muted">{{ t('adminUi.passwordHint') }}</p>
        <label
          >{{ t('adminUi.currentPassword')
          }}<input
            v-model="oldPassword"
            type="password"
            autocomplete="current-password"
            required
            maxlength="1024" /></label
        ><label
          >{{ t('adminUi.newPassword')
          }}<input
            v-model="newPassword"
            type="password"
            autocomplete="new-password"
            minlength="12"
            maxlength="1024"
            required /></label
        ><label
          >{{ t('adminUi.confirmPassword')
          }}<input
            v-model="confirmPassword"
            type="password"
            autocomplete="new-password"
            minlength="12"
            maxlength="1024"
            required
        /></label>
        <p v-if="passwordValidation" class="field-error">
          {{ passwordValidation }}
        </p>
        <RequestStatus
          :state="passwordRequest.state.value"
          :error="passwordRequest.error.value"
          @retry="changePassword"
        /><button class="button primary" type="submit" :disabled="passwordRequest.pending.value">
          {{ t('adminUi.changePassword') }}
        </button>
      </form>
    </div>
  </section>
</template>
