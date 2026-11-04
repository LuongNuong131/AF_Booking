<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { useAuthStore } from '../stores/auth'
import { timeouts } from '../config/timeouts'
import type { PushPublicKey } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
const { t } = useI18n(),
  auth = useAuthStore(),
  busy = ref(false),
  message = ref('')
const supported =
  typeof window !== 'undefined' &&
  window.isSecureContext &&
  'serviceWorker' in navigator &&
  'PushManager' in window &&
  typeof Notification !== 'undefined'
const keys = useRequest(
  async ({ signal, timeoutMs }) =>
    (await api.get<PushPublicKey>('/push/public-key', { signal, timeout: timeoutMs })).data,
  { timeoutMs: timeouts.profile },
)
const enabled = computed(() => auth.user?.settings?.web_push_enabled === true)
const mutation = useRequest(
  async ({ signal, timeoutMs }, action: 'subscribe' | 'unsubscribe', body: unknown) =>
    action === 'subscribe'
      ? (await api.post('/push/subscribe', body, { signal, timeout: timeoutMs })).data
      : (await api.delete('/push/subscribe', { data: body, signal, timeout: timeoutMs })).data,
  { timeoutMs: timeouts.profile },
)
async function enable() {
  if (busy.value || !supported || !keys.data.value?.public_key) return
  busy.value = true
  message.value = ''
  try {
    const permission =
      Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission()
    if (permission !== 'granted') {
      message.value = t('taskUi.notificationsDenied')
      return
    }
    const registration = await navigator.serviceWorker.getRegistration()
    if (!registration?.active) {
      message.value = t('opsUi.pushNeedsApp')
      return
    }
    const publicKey = keys.data.value.public_key.replace(/-/g, '+').replace(/_/g, '/')
    const bytes = new Uint8Array(
      Array.from(atob(publicKey + '='.repeat((4 - (publicKey.length % 4)) % 4)), (c) =>
        c.charCodeAt(0),
      ),
    ).buffer
    const subscription =
      (await registration.pushManager.getSubscription()) ??
      (await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: bytes,
      }))
    const value = subscription.toJSON(),
      epoch = auth.epoch
    const result = await mutation.run('subscribe', {
      endpoint: subscription.endpoint,
      keys: value.keys,
    })
    if (result && epoch === auth.epoch && auth.user) {
      auth.user = {
        ...auth.user,
        settings: { ...(auth.user.settings ?? {}), web_push_enabled: true },
      }
      message.value = t('opsUi.pushEnabled')
    } else if (mutation.error.value?.code === 'NOT_FOUND') {
      await subscription.unsubscribe()
      message.value = t('opsUi.pushRebind')
    }
  } catch {
    message.value = t('opsUi.pushFailure')
  } finally {
    busy.value = false
  }
}
async function disable() {
  if (busy.value) return
  busy.value = true
  message.value = ''
  try {
    const subscription = await (
      await navigator.serviceWorker.getRegistration()
    )?.pushManager.getSubscription()
    const epoch = auth.epoch
    if (subscription) {
      const result = await mutation.run('unsubscribe', { endpoint: subscription.endpoint })
      if (!result) return
      await subscription.unsubscribe()
    } else {
      await api.patch(
        '/profile',
        { settings: { web_push_enabled: false } },
        { timeout: timeouts.profile },
      )
    }
    if (epoch === auth.epoch && auth.user)
      auth.user = {
        ...auth.user,
        settings: { ...(auth.user.settings ?? {}), web_push_enabled: false },
      }
    message.value = t('opsUi.pushDisabled')
  } catch {
    message.value = t('opsUi.pushFailure')
  } finally {
    busy.value = false
  }
}
onMounted(() => void keys.run())
</script>
<template>
  <section class="background-push-settings">
    <h2>{{ t('opsUi.backgroundPush') }}</h2>
    <p class="muted">{{ t('opsUi.pushHint') }}</p>
    <p v-if="!supported" class="muted">{{ t('opsUi.pushUnsupported') }}</p>
    <p v-else-if="keys.data.value && !keys.data.value.enabled" class="muted">
      {{ t('opsUi.pushNotConfigured') }}
    </p>
    <p>{{ t(enabled ? 'opsUi.pushEnabled' : 'opsUi.pushDisabled') }}</p>
    <div class="admin-form-actions">
      <button
        type="button"
        class="button"
        :disabled="busy || !supported || !keys.data.value?.enabled"
        @click="enable"
      >
        {{ t(enabled ? 'opsUi.refreshPush' : 'opsUi.enablePush') }}</button
      ><button
        v-if="enabled"
        type="button"
        class="button"
        :disabled="busy || !supported"
        @click="disable"
      >
        {{ t('opsUi.disablePush') }}
      </button>
    </div>
    <p v-if="message" role="status">{{ message }}</p>
    <RequestStatus
      :state="keys.state.value"
      :error="keys.error.value"
      @retry="keys.run()"
    /><RequestStatus :state="mutation.state.value" :error="mutation.error.value" />
  </section>
</template>
