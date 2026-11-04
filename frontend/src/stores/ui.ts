import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { readStorage, writeStorage } from '../utils/storage'
import { timeouts } from '../config/timeouts'

export type Theme = 'system' | 'light' | 'dark'
export type RefreshReason = 'reconnect' | 'visible' | 'retry' | 'catalogue'
interface Notice {
  id: number
  kind: 'info' | 'error' | 'success'
  message: string
  scope: 'workspace' | 'session'
}
export const useUiStore = defineStore('ui', () => {
  const stored = readStorage('localStorage', 'booking.theme')
  const theme = ref<Theme>(stored === 'dark' || stored === 'light' ? stored : 'system')
  const systemDark = ref(false)
  const resolvedTheme = computed(() =>
    theme.value === 'system' ? (systemDark.value ? 'dark' : 'light') : theme.value,
  )
  const notices = ref<Notice[]>([])
  const paletteOpen = ref(false)
  const shortcutHelp = ref(false)
  const taskModalOpen = ref(false)
  const routeLoading = ref(false)
  const routeFailed = ref(false)
  const pendingPath = ref('/')
  const refreshVersion = ref(0)
  const refreshReason = ref<RefreshReason>('retry')
  let noticeId = 0
  const noticeTimers = new Map<number, ReturnType<typeof setTimeout>>()

  function applyTheme(): void {
    document.documentElement.dataset.theme = resolvedTheme.value
    document.documentElement.classList.toggle('dark', resolvedTheme.value === 'dark')
  }
  function setTheme(value: Theme): void {
    theme.value = value
    writeStorage('localStorage', 'booking.theme', value)
    applyTheme()
  }
  function toggleTheme(): void {
    setTheme(resolvedTheme.value === 'dark' ? 'light' : 'dark')
  }
  function startTheme(): () => void {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const changed = () => {
      systemDark.value = media.matches
      applyTheme()
    }
    const storage = (event: StorageEvent) => {
      if (event.key !== 'booking.theme') return
      theme.value =
        event.newValue === 'light' || event.newValue === 'dark' ? event.newValue : 'system'
      applyTheme()
    }
    changed()
    media.addEventListener('change', changed)
    window.addEventListener('storage', storage)
    return () => {
      media.removeEventListener('change', changed)
      window.removeEventListener('storage', storage)
    }
  }
  function dismiss(id: number): void {
    clearTimeout(noticeTimers.get(id))
    noticeTimers.delete(id)
    notices.value = notices.value.filter((n) => n.id !== id)
  }
  function notify(
    message: string,
    kind: Notice['kind'] = 'info',
    scope: Notice['scope'] = 'workspace',
  ): void {
    if (notices.value.some((n) => n.message === message)) return
    const id = ++noticeId
    notices.value.push({ id, message, kind, scope })
    while (notices.value.length > 4) dismiss(notices.value[0]!.id)
    noticeTimers.set(
      id,
      setTimeout(() => dismiss(id), timeouts.notice),
    )
  }
  function requestRefresh(reason: RefreshReason): void {
    refreshReason.value = reason
    refreshVersion.value++
  }
  function clearNotices(scope?: Notice['scope']): void {
    for (const notice of [...notices.value]) {
      if (!scope || notice.scope === scope) dismiss(notice.id)
    }
  }
  return {
    theme,
    resolvedTheme,
    notices,
    shortcutHelp,
    paletteOpen,
    taskModalOpen,
    routeLoading,
    routeFailed,
    pendingPath,
    refreshVersion,
    refreshReason,
    startTheme,
    setTheme,
    toggleTheme,
    notify,
    dismiss,
    requestRefresh,
    clearNotices,
  }
})
