import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'
export const usePwaStore = defineStore('pwa', () => {
  const updateReady = ref(false),
    registration = shallowRef<ServiceWorkerRegistration | null>(null),
    reloading = ref(false),
    controllerChanged = ref(false)
  return { updateReady, registration, reloading, controllerChanged }
})
