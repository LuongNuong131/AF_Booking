import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api/client'
import { parseLogin, parseUser } from '../api/auth-payload'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import { readStorage, writeStorage } from '../utils/storage'
import { validTimeZone } from '../utils/dateTime'
import type { LoginRequest, PublicUser } from '../types/api.generated'

const tokenKey = 'booking.access_token'
export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(readStorage('sessionStorage', tokenKey))
  const user = ref<PublicUser | null>(null)
  const epoch = ref(0)
  const ready = ref(!token.value)
  const signingOut = ref(false)
  const isAuthenticated = computed(() => !!token.value && !!user.value && user.value.is_active)
  const timezone = computed(() =>
    validTimeZone(
      user.value?.settings?.timezone,
      validTimeZone(Intl.DateTimeFormat().resolvedOptions().timeZone),
    ),
  )
  let restoring: Promise<boolean> | null = null
  const loginRequest = useRequest(
    async ({ signal, timeoutMs }, credentials: LoginRequest) =>
      parseLogin(
        (
          await api.post<unknown>('/auth/login', credentials, {
            signal,
            timeout: timeoutMs,
            skipAuth: true,
          })
        ).data,
      ),
    { timeoutMs: timeouts.profile },
  )
  const restoreRequest = useRequest(
    async ({ signal, timeoutMs }) =>
      parseUser((await api.get<unknown>('/auth/me', { signal, timeout: timeoutMs })).data),
    { timeoutMs: timeouts.profile },
  )
  const logoutRequest = useRequest(
    async ({ signal, timeoutMs }) =>
      (await api.post('/auth/logout', undefined, { signal, timeout: timeoutMs })).data as unknown,
    { timeoutMs: timeouts.profile },
  )

  function clear(): void {
    epoch.value++
    loginRequest.cancel()
    restoreRequest.cancel()
    loginRequest.data.value = undefined
    loginRequest.error.value = null
    loginRequest.state.value = 'idle'
    restoreRequest.data.value = undefined
    restoreRequest.error.value = null
    restoreRequest.state.value = 'idle'
    token.value = null
    user.value = null
    ready.value = true
    restoring = null
    writeStorage('sessionStorage', tokenKey, null)
  }
  async function login(credentials: LoginRequest): Promise<boolean> {
    const generation = ++epoch.value
    restoreRequest.cancel()
    const result = await loginRequest.run(credentials)
    if (!result || generation !== epoch.value || !result.user.is_active) return false
    loginRequest.data.value = undefined
    user.value = result.user
    token.value = result.access_token
    ready.value = true
    writeStorage('sessionStorage', tokenKey, result.access_token)
    return true
  }
  async function ensureSession(): Promise<boolean> {
    if (ready.value) return isAuthenticated.value
    if (restoring) return restoring
    const generation = epoch.value
    restoring = (async () => {
      const result = await restoreRequest.run()
      if (generation !== epoch.value) return isAuthenticated.value
      if (result?.is_active) user.value = result
      restoreRequest.data.value = undefined
      ready.value = true
      return isAuthenticated.value
    })().finally(() => {
      restoring = null
    })
    return restoring
  }
  async function retryRestore(): Promise<boolean> {
    if (!token.value) return false
    ready.value = false
    return ensureSession()
  }
  async function logout(): Promise<void> {
    if (signingOut.value) return
    signingOut.value = true
    try {
      if (token.value) await logoutRequest.run()
    } finally {
      clear()
      signingOut.value = false
    }
  }
  function expire(): void {
    clear()
    logoutRequest.cancel()
  }
  return {
    token,
    user,
    epoch,
    ready,
    signingOut,
    timezone,
    isAuthenticated,
    loginRequest,
    restoreRequest,
    logoutRequest,
    login,
    logout,
    ensureSession,
    retryRestore,
    expire,
  }
})
