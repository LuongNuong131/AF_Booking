<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatBookingKey } from '../utils/bookingKey'
import { useUiStore } from '../stores/ui'
import BaseIcon from './BaseIcon.vue'
const props = defineProps<{ bookingKey: string }>()
const { t } = useI18n()
const ui = useUiStore()
const display = computed(() => formatBookingKey(props.bookingKey))
async function copy() {
  try {
    await navigator.clipboard.writeText(display.value)
    ui.notify(t('common.copied'), 'success')
  } catch {
    ui.notify(t('common.copyFailed'), 'error')
  }
}
</script>
<template>
  <span class="booking-key"
    ><span>{{ display }}</span
    ><button
      type="button"
      class="icon-button small"
      :aria-label="t('copy_key')"
      :title="t('copy_key')"
      @click="copy"
    >
      <BaseIcon name="copy" /></button
  ></span>
</template>
