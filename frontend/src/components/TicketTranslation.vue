<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import type { TranslationConfig, TranslationResult } from '../types/api.generated'
import { timeouts } from '../config/timeouts'
import { englishTicket } from '../utils/ticket'
import RequestStatus from './RequestStatus.vue'
const props = defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ apply: [value: string] }>()
const { t } = useI18n(), source = ref(''), result = ref('')
const config = useRequest(async ({ signal, timeoutMs }) => (await api.get<TranslationConfig>('/work-tasks/translation/config', { signal, timeout: timeoutMs })).data, { timeoutMs: timeouts.list })
const translation = useRequest(async ({ signal, timeoutMs }, text: string) => (await api.post<TranslationResult>('/work-tasks/translate', { text }, { signal, timeout: timeoutMs })).data, { timeoutMs: 15000 })
const googleUrl = computed(() => `https://translate.google.com/?sl=vi&tl=en&text=${encodeURIComponent(source.value)}&op=translate`)
watch(source, () => { translation.cancel(); result.value = '' })
async function translate() { const value = await translation.run(source.value.trim()); if (value) result.value = value.text }
function open(event: Event) { if ((event.target as HTMLDetailsElement).open && !config.data.value) void config.run() }
</script>
<template>
  <details class="ticket-translation" @toggle="open">
    <summary>{{ t('ticketCompose.translation') }}</summary>
    <p class="input-hint">{{ t('ticketCompose.translationHint') }}</p>
    <label class="field-label">{{ t('ticketCompose.vietnamese') }}<textarea v-model="source" maxlength="2000" rows="3" :disabled="disabled" /></label>
    <div class="ticket-actions">
      <button v-if="config.data.value?.enabled" type="button" class="button" :disabled="disabled || !source.trim() || translation.pending.value" @click="translate">{{ t('ticketCompose.translate') }}</button>
      <a v-if="source.trim() && !disabled" class="text-button" :href="googleUrl" target="_blank" rel="noopener noreferrer">{{ t('ticketCompose.googleTranslate') }}</a>
    </div>
    <RequestStatus :state="config.state.value" :error="config.error.value" @retry="config.run" />
    <RequestStatus :state="translation.state.value" :error="translation.error.value" @retry="translate" />
    <label class="field-label">{{ t('ticketCompose.reviewTranslation') }}<textarea v-model="result" maxlength="2000" rows="3" :disabled="disabled || translation.pending.value" /></label>
    <button type="button" class="button" :disabled="disabled || !englishTicket(result) || translation.pending.value" @click="emit('apply', result.trim())">{{ t('ticketCompose.useTranslation') }}</button>
  </details>
</template>
