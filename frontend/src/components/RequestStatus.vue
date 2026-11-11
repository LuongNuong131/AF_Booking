<script setup lang="ts">
import { getCurrentInstance } from 'vue'
import { useI18n } from 'vue-i18n'
import { errorMessage } from '../api/request-error'
import type { RequestFailure } from '../api/errors'
const { t } = useI18n()
const instance = getCurrentInstance()
defineProps<{
  state: string
  error?: RequestFailure | null
  canCancel?: boolean
}>()
defineEmits<{ retry: []; cancel: [] }>()
</script>
<template>
  <div class="request-status" aria-live="polite">
    <p v-if="state === 'loading' && !error" class="request-loading" role="status">
      <span aria-hidden="true" class="request-spinner" />{{ t('common.loading') }}
    </p>
    <p
      v-if="(state === 'loading' || state === 'slow') && error?.code === 'SERVICE_BUSY'"
      role="status"
    >
      {{ t('service_busy') }}
    </p>
    <p v-else-if="state === 'slow'" role="status">{{ t('request_slow') }}</p>
    <div v-if="state === 'error' || state === 'timeout'" class="inline-error" role="alert">
      <p>{{ errorMessage(error || null) || t('request_timeout') }}</p>
      <button v-if="instance?.vnode.props?.onRetry" type="button" class="text-button" @mousedown.prevent @click="$emit('retry')">
        {{ t('request_retry') }}
      </button>
    </div>
    <button
      v-if="canCancel && (state === 'loading' || state === 'slow')"
      type="button"
      class="text-button cancel-request"
      @mousedown.prevent
      @click="$emit('cancel')"
    >
      {{ t('common.cancel') }}
    </button>
  </div>
</template>
