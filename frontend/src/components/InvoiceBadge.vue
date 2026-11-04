<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
defineProps<{
  state: string
  count: number
  preview?: string[]
  done?: boolean
}>()
</script>
<template>
  <span class="invoice-badge" :class="state">
    <template v-if="state === 'has_invoice'"
      >{{ preview?.slice(0, 2).join(', ') || t('invoiceUi.count', { n: count })
      }}<span v-if="preview?.length && count > 2"> +{{ count - 2 }}</span></template
    >
    <span v-else-if="state === 'no_invoice'">{{ t('invoice_state_none') }}</span>
    <span v-else-if="done">{{ t('invoice_state_unknown') }}</span>
    <span v-else>—</span>
  </span>
</template>
