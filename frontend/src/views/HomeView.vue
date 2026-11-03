<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useBookingsStore } from '../stores/bookings'
import BookingWorkspace from '../components/BookingWorkspace.vue'
import MyBookings from '../components/MyBookings.vue'
const { t } = useI18n(),
  store = useBookingsStore()
const initialKey = store.homeKey || undefined
const workspace = ref<InstanceType<typeof BookingWorkspace> | null>(null)
function open(key: string) {
  void workspace.value?.open(key)
  workspace.value?.focus()
}
</script>
<template>
  <section class="home-view">
    <header class="page-heading home-heading">
      <div>
        <p class="page-eyebrow">{{ t('bookingUi.homeEyebrow') }}</p>
        <h1>{{ t('pages.homeTitle') }}</h1>
        <p>{{ t('bookingUi.homeIntro') }}</p>
      </div>
      <span class="workspace-date">{{ t('bookingUi.keyboardReady') }}</span>
    </header>
    <div class="booking-workspace-grid">
      <BookingWorkspace ref="workspace" :initial-key="initialKey" /><MyBookings @open="open" />
    </div>
  </section>
</template>
