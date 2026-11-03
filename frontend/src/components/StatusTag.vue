<script setup lang="ts">
import { computed } from 'vue'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'
import { useI18n } from 'vue-i18n'
import type { StatusSummary } from '../types/api.generated'
const props = defineProps<{ status?: StatusSummary | null }>()
const { t } = useI18n()
const colors: Record<string, 'success' | 'danger' | 'warning' | 'primary' | 'info'> = {
  DONE: 'success',
  REJECTION: 'danger',
  PARKING: 'warning',
  BUNDLE: 'primary',
  HRS_PREVIEW: 'info',
}
const type = computed(() => colors[props.status?.code || ''] || 'info')
</script>
<template>
  <ElTag :type="type" effect="light" size="small">{{ status?.label || t('common.unknown') }}</ElTag>
</template>
