import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { Task } from '../types/api.generated'

// Prompt 7B/5B will connect the task endpoints. No request is sent to a reserved API.
export const useTasksStore = defineStore('tasks', () => {
  const dueTasks = ref<Task[]>([])
  const dirty = ref(false)
  const dueCount = computed(() => dueTasks.value.length)
  function setDueTasks(items: Task[]): void {
    dueTasks.value = items
    dirty.value = false
  }
  function invalidate(): void {
    dirty.value = true
  }
  function reset(): void {
    dueTasks.value = []
    dirty.value = false
  }
  return { dueTasks, dueCount, dirty, setDueTasks, invalidate, reset }
})
