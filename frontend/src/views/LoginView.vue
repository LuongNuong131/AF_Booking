<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ElButton,
  ElForm,
  ElFormItem,
  ElInput,
  type FormInstance,
  type InputInstance,
} from 'element-plus'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/input/style/css'
import '../login.css'
import { useAuthStore } from '../stores/auth'
import { safeRedirect } from '../utils/navigation'
import BaseIcon from '../components/BaseIcon.vue'
import BrandMark from '../components/BrandMark.vue'
import ThemeMenu from '../components/ThemeMenu.vue'
import LanguageSelect from '../components/LanguageSelect.vue'
import { useWarmup } from '../composables/useWarmup'
import RequestStatus from '../components/RequestStatus.vue'
const { t } = useI18n()
const warmup = useWarmup()
const auth = useAuthStore()
const route = useRoute(),
  router = useRouter()
const form = ref<FormInstance>(),
  username = ref<InputInstance>()
const credentials = reactive({ username: '', password: '' })
async function submit() {
  if (auth.loginRequest.pending) return
  const valid = await form.value?.validate().catch(() => false)
  if (!valid) return
  if (
    await auth.login({
      username: credentials.username.trim(),
      password: credentials.password,
    })
  ) {
    credentials.password = ''
    await router.replace(safeRedirect(route.query.redirect))
  }
}
async function restore() {
  if (await auth.retryRestore()) await router.replace(safeRedirect(route.query.redirect))
}
onMounted(async () => {
  await nextTick()
  username.value?.focus()
})
onBeforeUnmount(() => {
  auth.loginRequest.cancel()
  credentials.password = ''
})
</script>
<template>
  <div class="login-page premium-login">
    <aside class="login-story">
      <RouterLink to="/" class="brand"
        ><BrandMark />
        <span
          >{{ t('app.name') }}<small>{{ t('app.workspace') }}</small></span
        ></RouterLink
      >
      <div class="story-copy">
        <h1>{{ t('auth.welcome') }}</h1>
        <p class="story-intro">{{ t('auth.intro') }}</p>
      </div>
      <div class="operations-illustration" aria-hidden="true">
        <div class="route-line">
          <span class="route-station">CDG</span>
          <svg viewBox="0 0 300 54" fill="none">
            <path d="M8 40C75 40 77 10 150 10S225 40 292 40" stroke="currentColor" stroke-dasharray="3 6" />
            <circle cx="8" cy="40" r="4" fill="currentColor" />
            <circle cx="292" cy="40" r="4" fill="currentColor" />
            <path d="m145 9 12 2-10 7 1-6-3-3Z" fill="currentColor" stroke="currentColor" stroke-linejoin="round" />
          </svg>
          <span class="route-station">YUL</span>
        </div>
        <div class="operations-ledger">
          <div class="ledger-heading"><span>{{ t('app.name') }}</span><BaseIcon name="folder" /></div>
          <div class="ledger-row"><span class="ledger-node complete"><BaseIcon name="check" /></span><div><strong>CW 2154927-YUL-2611</strong><span class="ledger-line long" /></div><span class="ledger-state complete" /></div>
          <div class="ledger-row"><span class="ledger-node"><BaseIcon name="clock" /></span><div><strong>CW 2154654-CDG-2611</strong><span class="ledger-line" /></div><span class="ledger-state" /></div>
          <div class="ledger-row"><span class="ledger-node"><BaseIcon name="folder" /></span><div><strong>CW 2154982-SGN-2611</strong><span class="ledger-line short" /></div><span class="ledger-state" /></div>
        </div>
      </div>
      <div class="story-bottom">
        <ul class="story-features">
          <li v-for="(key, index) in ['featureOne', 'featureTwo', 'featureThree']" :key="key">
            <BaseIcon :name="['folder', 'globe', 'shield'][index]!" />{{ t(`auth.${key}`) }}
          </li>
        </ul>
        <p class="story-footer">{{ t('auth.security') }}</p>
      </div>
    </aside>
    <main class="login-main">
      <div class="login-toolbar"><LanguageSelect /><ThemeMenu /></div>
      <div class="login-form-wrap">
        <div class="mobile-brand brand">
          <BrandMark />
          <span>{{ t('app.name') }}</span>
        </div>
        <div class="login-form-symbol" aria-hidden="true"><BaseIcon name="shield" /></div>
        <p class="login-kicker">{{ t('app.workspace') }}</p>
        <h2>{{ t('auth.signIn') }}</h2>
        <p class="login-subtitle">{{ t('auth.subtitle') }}</p>
        <div
          v-if="auth.token && !auth.isAuthenticated && auth.restoreRequest.error"
          class="restore-hint"
          role="alert"
        >
          <p>{{ t('auth.restoreError') }}</p>
          <button
            type="button"
            class="text-button"
            :disabled="auth.restoreRequest.pending"
            @click="restore"
          >
            {{ t('auth.restoreRetry') }}
          </button>
        </div>
        <ElForm
          ref="form"
          :model="credentials"
          label-position="top"
          size="large"
          @submit.prevent="submit"
          ><ElFormItem
            prop="username"
            :label="t('auth.username')"
            :rules="[
              {
                required: true,
                whitespace: true,
                message: t('auth.usernameRequired'),
                trigger: 'blur',
              },
            ]"
            ><ElInput
              ref="username"
              v-model="credentials.username"
              name="username"
              autocomplete="username"
              :maxlength="50"
              :placeholder="t('auth.usernamePlaceholder')"
              :aria-label="t('auth.username')" /></ElFormItem
          ><ElFormItem
            prop="password"
            :label="t('auth.password')"
            :rules="[
              {
                required: true,
                message: t('auth.passwordRequired'),
                trigger: 'blur',
              },
            ]"
            ><ElInput
              v-model="credentials.password"
              name="password"
              type="password"
              autocomplete="current-password"
              show-password
              :maxlength="1024"
              :placeholder="t('auth.passwordPlaceholder')"
              :aria-label="t('auth.password')" /></ElFormItem
          ><ElButton
            type="primary"
            native-type="submit"
            class="login-submit"
            :disabled="auth.loginRequest.pending"
            ><span>{{ t(auth.loginRequest.pending ? 'auth.signingIn' : 'auth.signIn') }}</span
            ><BaseIcon v-if="!auth.loginRequest.pending" name="arrow" /><span
              v-else
              class="button-spinner"
              aria-hidden="true" /></ElButton
          ><RequestStatus
            :state="auth.loginRequest.state"
            :error="auth.loginRequest.error"
            can-cancel
            @retry="submit"
            @cancel="auth.loginRequest.cancel"
        /></ElForm>
        <p class="account-note"><BaseIcon name="shield" />{{ t('auth.noSignup') }}</p>
      </div>
      <footer class="login-footer">
        <span class="login-service-status" role="status" :class="warmup.state.value"
          ><span class="status-dot" />{{ t(`outboxUi.warm_${warmup.state.value}`) }}</span
        ><span>{{ t('app.name') }}</span>
      </footer>
    </main>
  </div>
</template>
