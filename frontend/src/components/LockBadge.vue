<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useRealtimeStore } from '../stores/realtime'
import BaseIcon from './BaseIcon.vue'
const props = defineProps<{ bookingKey: string }>()
const { t } = useI18n(),
  auth = useAuthStore(),
  realtime = useRealtimeStore()
const holder = computed(() => realtime.locks[props.bookingKey])
</script>
<template>
  <p v-if="holder && holder.user_id !== auth.user?.id" class="lock-badge" role="status">
    <BaseIcon name="user" />{{ t('lock_tag', { user: holder.user_name }) }}
  </p>
</template>
