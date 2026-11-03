<script setup lang="ts">
import BaseIcon from './BaseIcon.vue'
defineProps<{ title: string; description?: string }>()
</script>
<template>
  <div class="empty-state">
    <span class="empty-icon"><BaseIcon name="inbox" /></span>
    <h3>{{ title }}</h3>
    <p v-if="description">{{ description }}</p>
    <slot />
  </div>
</template>
