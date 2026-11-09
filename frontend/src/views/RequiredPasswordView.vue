<script setup lang="ts">
import { onScopeDispose, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useRequest } from '../composables/useRequest'
import { api } from '../api/client'
import { timeouts } from '../config/timeouts'
import RequestStatus from '../components/RequestStatus.vue'
import LanguageSelect from '../components/LanguageSelect.vue'
const { t } = useI18n(),
  auth = useAuthStore(),
  router = useRouter()
const oldPassword = ref(''),
  newPassword = ref(''),
  confirm = ref(''),
  validation = ref('')
const request = useRequest(
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
async function save() {
  validation.value = ''
  if (newPassword.value !== confirm.value) {
    validation.value = t('adminUi.passwordMismatch')
    return
  }
  if (
    newPassword.value.trim().toLocaleLowerCase() ===
    auth.user?.username.trim().toLocaleLowerCase()
  ) {
    validation.value = t('securityUi.passwordRule')
    return
  }
  if (request.pending.value) return
  const result = await request.run()
  if (result) {
    oldPassword.value = ''
    newPassword.value = ''
    confirm.value = ''
    auth.expire()
    await router.replace({ name: 'login' })
  }
}
onScopeDispose(() => {
  oldPassword.value = ''
  newPassword.value = ''
  confirm.value = ''
})
async function signOut() {
  await auth.logout()
  await router.replace({ name: 'login' })
}
</script>
<template>
  <main class="required-password-page">
    <LanguageSelect />
    <form class="admin-panel" @submit.prevent="save">
      <h1>{{ t('securityUi.changePassword') }}</h1>
      <p>{{ t('securityUi.firstLogin') }}</p>
      <p class="muted">{{ t('securityUi.passwordRule') }}</p>
      <label class="field-label"
        >{{ t('securityUi.currentPassword')
        }}<input
          v-model="oldPassword"
          type="password"
          required
          maxlength="1024"
          autocomplete="current-password"
      /></label>
      <label class="field-label"
        >{{ t('securityUi.newPassword')
        }}<input
          v-model="newPassword"
          type="password"
          required
          minlength="10"
          maxlength="128"
          autocomplete="new-password"
      /></label>
      <label class="field-label"
        >{{ t('securityUi.confirmPassword')
        }}<input
          v-model="confirm"
          type="password"
          required
          minlength="10"
          maxlength="128"
          autocomplete="new-password"
      /></label>
      <p v-if="validation" role="alert" class="field-error">{{ validation }}</p>
      <RequestStatus :state="request.state.value" :error="request.error.value" />
      <div class="admin-form-actions">
        <button type="submit" class="button primary" :disabled="request.pending.value">
          {{ t('securityUi.savePassword') }}</button
        ><button type="button" class="button" @click="signOut">
          {{ t('securityUi.signOut') }}
        </button>
      </div>
    </form>
  </main>
</template>
