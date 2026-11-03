<script setup lang="ts">
import { onErrorCaptured, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
const props = defineProps<{ resetKey?: string }>()
const { t } = useI18n()
const failed = ref(false)
const generation = ref(0)
onErrorCaptured(() => {
  failed.value = true
  return false
})
function retry() {
  failed.value = false
  generation.value++
}
watch(() => props.resetKey, retry)
</script>
<template>
  <section v-if="failed" class="boundary-card" role="alert">
    <h2>{{ t('boundary.title') }}</h2>
    <p>{{ t('boundary.body') }}</p>
    <button type="button" class="button primary" @click="retry">
      {{ t('boundary.retry') }}
    </button>
  </section>
  <div v-else :key="generation" class="boundary-content"><slot /></div>
</template>
