<script setup lang="ts">
import { computed } from 'vue'
import { noteHighlight } from '../utils/noteHighlight'
const props = defineProps<{ text: string; query: string }>(),
  parts = computed(() => noteHighlight(props.text, props.query))
</script>
<template>
  <span class="note-highlight"
    ><template v-for="(part, i) in parts" :key="i"
      ><mark v-if="part.match">{{ part.text }}</mark
      ><template v-else>{{ part.text }}</template></template
    ></span
  >
</template>
