<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ name: string; small?: boolean }>()
const initials = computed(() =>
  props.name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => Array.from(word)[0] || '')
    .join('')
    .toUpperCase(),
)
</script>
<template>
  <span class="user-avatar" :class="{ small }" aria-hidden="true">{{ initials }}</span>
</template>
