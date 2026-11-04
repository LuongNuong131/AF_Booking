import { defineStore } from 'pinia'
import { ref } from 'vue'
export const useSystemHealthStore = defineStore('system-health', () => {
  const degraded = ref(false)
  return { degraded, reset: () => (degraded.value = false) }
})
