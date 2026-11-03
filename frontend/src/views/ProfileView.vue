<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useUiStore, type Theme } from '../stores/ui'
import UserAvatar from '../components/UserAvatar.vue'
const { t } = useI18n()
const auth = useAuthStore(),
  ui = useUiStore()
function updateTheme(event: Event) {
  ui.setTheme((event.target as HTMLSelectElement).value as Theme)
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
    </div>
  </section>
</template>
