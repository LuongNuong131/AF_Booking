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
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { safeRedirect } from '../utils/navigation'
import BaseIcon from '../components/BaseIcon.vue'
import ThemeMenu from '../components/ThemeMenu.vue'
import RequestStatus from '../components/RequestStatus.vue'
const { t } = useI18n()
const auth = useAuthStore(),
  ui = useUiStore()
const route = useRoute(),
  router = useRouter()
const form = ref<FormInstance>(),
  username = ref<InputInstance>()
const credentials = reactive({ username: '', password: '' })
async function submit() {
  if (auth.loginRequest.pending) return
  const valid = await form.value?.validate().catch(() => false)
  if (!valid) return
  if (await auth.login({ username: credentials.username.trim(), password: credentials.password })) {
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
  <div class="login-page">
    <aside class="login-story">
      <RouterLink to="/" class="brand"
        ><span class="brand-mark" aria-hidden="true">{{ t('app.initial') }}</span
        ><span
          >{{ t('app.name') }}<small>{{ t('app.workspace') }}</small></span
        ></RouterLink
      >
      <div class="story-copy">
        <p class="eyebrow">{{ t('auth.eyebrow') }}</p>
        <h1>{{ t('auth.welcome') }}</h1>
        <p class="story-intro">{{ t('auth.intro') }}</p>
        <ul class="story-features">
          <li v-for="key in ['featureOne', 'featureTwo', 'featureThree']" :key="key">
            <span class="story-check"><BaseIcon name="check" /></span>{{ t(`auth.${key}`) }}
          </li>
        </ul>
      </div>
      <div class="story-graphic" aria-hidden="true">
        <div class="orbit orbit-one" />
        <div class="orbit orbit-two" />
        <div class="orbit orbit-three" />
        <span class="orbit-point point-one" /><span class="orbit-point point-two" /><span
          class="orbit-point point-three"
        />
      </div>
      <p class="story-footer">{{ t('auth.security') }}</p>
    </aside>
    <main class="login-main">
      <div class="login-toolbar"><ThemeMenu /></div>
      <div class="login-form-wrap">
        <div class="mobile-brand brand">
          <span class="brand-mark" aria-hidden="true">{{ t('app.initial') }}</span
          ><span>{{ t('app.name') }}</span>
        </div>
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
            :rules="[{ required: true, message: t('auth.passwordRequired'), trigger: 'blur' }]"
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
        <span>{{ t('app.name') }}</span
        ><button type="button" class="text-button" @click="ui.toggleTheme">
          {{ t(ui.resolvedTheme === 'dark' ? 'theme.switchLight' : 'theme.switchDark') }}
        </button>
      </footer>
    </main>
  </div>
</template>
