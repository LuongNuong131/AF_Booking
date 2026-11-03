<script setup lang="ts">
import { onScopeDispose, watch, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTasksStore } from '../stores/tasks'
import { timeouts } from '../config/timeouts'
const props = defineProps<{
  bookingKey: string
  strong?: boolean
  nonce: number
  days?: number | null
}>()
const { t } = useI18n(),
  tasks = useTasksStore(),
  visible = ref(true)
let timer: ReturnType<typeof setTimeout> | undefined
watch(
  () => props.nonce,
  () => {
    visible.value = true
    clearTimeout(timer)
    timer = setTimeout(() => {
      visible.value = false
    }, timeouts.taskSuggestion)
  },
  { immediate: true },
)
onScopeDispose(() => clearTimeout(timer))
function open(days = props.days ?? 1) {
  tasks.openDialog(props.bookingKey, undefined, 'create', days)
  visible.value = false
}
</script>
<template>
  <aside v-if="visible" class="task-suggestion-bar" :class="{ strong }" role="status">
    <button type="button" class="text-button" @click="open()">
      {{ t('task_prompt') }}
    </button>
    <div>
      <button
        v-for="days in [1, 2, 3, 5, 7]"
        :key="days"
        type="button"
        class="task-suggestion-chip"
        @click="open(days)"
      >
        {{
          t(days === 1 ? 'taskUi.tomorrow' : days === 7 ? 'taskUi.week' : 'taskUi.days', { days })
        }}
      </button>
    </div>
  </aside>
</template>
