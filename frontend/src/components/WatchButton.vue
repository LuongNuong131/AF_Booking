<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCollaborationStore } from '../stores/collaboration'
const props = defineProps<{
    bookingKey: string
    watching?: boolean
    disabled?: boolean
  }>(),
  store = useCollaborationStore(),
  { t } = useI18n()
watch(
  () => [props.bookingKey, props.watching] as const,
  ([key, value]) => {
    if (value !== undefined) store.seed(key, value)
  },
  { immediate: true },
)
const selected = computed(() => store.watched[props.bookingKey] ?? props.watching ?? false)
</script>
<template>
  <button
    type="button"
    class="button watch-button"
    :aria-pressed="selected"
    :disabled="disabled || store.pending.includes(bookingKey)"
    @click.stop="store.toggle(bookingKey, selected)"
  >
    {{ t(selected ? 'collabUi.unwatch' : 'collabUi.watch') }}
  </button>
</template>
