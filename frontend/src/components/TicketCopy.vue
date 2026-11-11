<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
const props = defineProps<{ title: string; message: string }>()
const { t } = useI18n(), copied = ref(''), fallback = ref('')
watch(() => [props.title, props.message], () => { copied.value = ''; fallback.value = '' })
async function copy(kind: 'title' | 'message' | 'all') {
  const value = kind === 'title' ? props.title : kind === 'message' ? props.message : `${props.title}\n\n${props.message}`
  copied.value = ''; fallback.value = ''
  try { await navigator.clipboard.writeText(value); copied.value = kind }
  catch { fallback.value = value }
}
</script>
<template>
  <div class="ticket-copy">
    <div class="ticket-actions"><button type="button" class="button" @click="copy('title')">{{ t('ticketCompose.copyTitle') }}</button><button type="button" class="button" @click="copy('message')">{{ t('ticketCompose.copyContent') }}</button><button type="button" class="button" @click="copy('all')">{{ t('ticketCompose.copyAll') }}</button></div>
    <p v-if="copied" role="status" class="ticket-success">{{ t('ticketCompose.copied') }}</p>
    <label v-if="fallback" class="field-label">{{ t('ticketCompose.manualCopy') }}<textarea :value="fallback" readonly rows="5" @focus="($event.target as HTMLTextAreaElement).select()" /></label>
  </div>
</template>
