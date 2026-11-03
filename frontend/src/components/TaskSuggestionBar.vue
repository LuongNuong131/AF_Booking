<script setup lang="ts">
import { onScopeDispose, watch, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTasksStore } from '../stores/tasks'
import { quickReminderDate, confirmation } from '../utils/taskDates'
import { zonedToday } from '../utils/summaryFilters'
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
const suggested = computed(() => {
  if (!props.days) return null
  const prefs = tasks.preferences
  const day = quickReminderDate(zonedToday(prefs.timezone), props.days, prefs.skip_weekends)
  return confirmation(day, prefs.default_remind_time, prefs.timezone)
})
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
  <aside
    v-if="visible && days != null"
    class="task-suggestion-bar"
    :class="{ strong }"
    role="status"
  >
    <button type="button" class="text-button" @click="open()">
      {{
        suggested && days
          ? t('guardUi.remindAfter', {
              days,
              when: `${suggested.weekday}, ${suggested.date} ${suggested.time}`,
            })
          : t('task_prompt')
      }}
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
