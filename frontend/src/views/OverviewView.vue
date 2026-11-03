<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEventListener } from '@vueuse/core'
import { formatDistanceToNowStrict } from 'date-fns'
import { ElAlert, ElButton, ElTag } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/tag/style/css'
import { useServiceStore } from '../stores'

const { t } = useI18n()
const services = useServiceStore()
const apiOnline = computed(() => services.state?.api === 'online')
const databaseOnline = computed(() => services.state?.database === 'connected')
const apiLabel = computed(() =>
  services.checking
    ? t('overview.checkingShort')
    : !services.state
      ? t('overview.unknown')
      : t(apiOnline.value ? 'overview.online' : 'overview.offline'),
)
const databaseLabel = computed(() =>
  services.checking
    ? t('overview.checkingShort')
    : !services.state
      ? t('overview.unknown')
      : t(
          databaseOnline.value
            ? 'overview.online'
            : services.state.database === 'not_configured'
              ? 'overview.notConfigured'
              : 'overview.offline',
        ),
)
const lastChecked = computed(() =>
  services.checkedAt
    ? t('overview.checked', {
        time: formatDistanceToNowStrict(services.checkedAt, {
          addSuffix: true,
        }),
      })
    : t('overview.neverChecked'),
)

onMounted(() => {
  void services.refresh()
})
useEventListener(window, 'online', () => {
  void services.refresh()
})
</script>

<template>
  <section class="hero">
    <p class="eyebrow">{{ t('overview.eyebrow') }}</p>
    <h1>{{ t('overview.title') }}</h1>
    <p class="hero-description">{{ t('overview.description') }}</p>
    <div class="hero-art" aria-hidden="true"><span></span><span></span><span></span></div>
  </section>
  <section class="setup-note">
    <span class="setup-symbol" aria-hidden="true">↗</span>
    <div>
      <h2>{{ t('overview.setupTitle') }}</h2>
      <p>{{ t('overview.setupBody') }}</p>
    </div>
  </section>
  <section class="services-section" :aria-busy="services.checking">
    <div class="section-heading">
      <div>
        <h2>{{ t('overview.servicesTitle') }}</h2>
        <p>{{ t('overview.servicesBody') }}</p>
      </div>
      <ElButton type="primary" :loading="services.checking" @click="services.refresh">
        {{ t(services.checking ? 'overview.checking' : 'overview.check') }}
      </ElButton>
    </div>
    <div class="service-grid" aria-live="polite">
      <article class="service-card">
        <div class="card-heading">
          <span class="service-symbol" aria-hidden="true">↔</span
          ><ElTag :type="apiOnline ? 'success' : 'info'" effect="light" round>{{ apiLabel }}</ElTag>
        </div>
        <h3>{{ t('overview.api') }}</h3>
        <p>{{ t('overview.apiDescription') }}</p>
      </article>
      <article class="service-card">
        <div class="card-heading">
          <span class="service-symbol" aria-hidden="true">▤</span
          ><ElTag :type="databaseOnline ? 'success' : 'info'" effect="light" round>{{
            databaseLabel
          }}</ElTag>
        </div>
        <h3>{{ t('overview.database') }}</h3>
        <p>{{ t('overview.databaseDescription') }}</p>
      </article>
    </div>
    <p class="last-checked" role="status">{{ lastChecked }}</p>
    <ElAlert
      v-if="services.state && !apiOnline"
      :title="t('overview.offlineHint')"
      type="warning"
      :closable="false"
      show-icon
    />
    <ElAlert
      v-else-if="services.state && !databaseOnline"
      :title="t('overview.databaseHint')"
      type="info"
      :closable="false"
      show-icon
    />
  </section>
</template>
