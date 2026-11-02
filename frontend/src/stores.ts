import { ref } from 'vue'
import { defineStore } from 'pinia'
import { checkServices, type ServiceState } from './api/health'

export const useServiceStore = defineStore('services', () => {
  const state = ref<ServiceState | null>(null)
  const checking = ref(false)
  const checkedAt = ref<Date | null>(null)

  async function refresh(): Promise<void> {
    if (checking.value) return
    checking.value = true
    try {
      state.value = await checkServices()
      checkedAt.value = new Date()
    } finally {
      checking.value = false
    }
  }
  return { state, checking, checkedAt, refresh }
})
