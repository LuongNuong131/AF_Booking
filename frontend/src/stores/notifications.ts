import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import type { NotificationList, NotificationNewData } from '../types/api.generated'
import type { RequestFailure } from '../api/errors'

export const useNotificationsStore = defineStore('notifications', () => {
  const items = ref<NotificationList['items']>([])
  const unread = ref(0)
  const actionError = ref<RequestFailure | null>(null)
  const marking = ref<number[]>([])
  const markingAll = ref(false)
  const listRequest = useRequest(
    async ({ signal, timeoutMs }) =>
      (
        await api.get<NotificationList>('/notifications', {
          params: { limit: 20 },
          signal,
          timeout: timeoutMs,
        })
      ).data,
    { timeoutMs: timeouts.list, retry: true },
  )
  const loading = computed(() => listRequest.pending.value)
  let epoch = 0
  let revision = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  const hints = new Set<number>()
  const mutations = new Set<() => void>()

  async function refresh(): Promise<void> {
    const generation = epoch
    const atRevision = revision
    const result = await listRequest.run()
    if (!result || generation !== epoch || atRevision !== revision) return
    items.value = result.items
    unread.value = result.unread_count
    for (const item of result.items) hints.add(item.id)
    while (hints.size > 1000) hints.delete(hints.values().next().value!)
  }
  function incoming(data: NotificationNewData): void {
    if (hints.has(data.id)) return
    hints.add(data.id)
    while (hints.size > 1000) hints.delete(hints.values().next().value!)
    unread.value++
    revision++
    listRequest.cancel()
    clearTimeout(timer)
    timer = setTimeout(() => {
      void refresh()
    }, timeouts.notificationDebounce)
  }
  async function markRead(id: number): Promise<boolean> {
    const item = items.value.find((n) => n.id === id)
    if (markingAll.value || item?.read_at || marking.value.includes(id)) return true
    const generation = epoch
    ++revision
    listRequest.cancel()
    const request = useRequest(
      async ({ signal, timeoutMs }) =>
        (
          await api.post(`/notifications/${id}/read`, undefined, {
            signal,
            timeout: timeoutMs,
          })
        ).data as unknown,
      { timeoutMs: timeouts.task },
    )
    mutations.add(request.cancel)
    const optimisticAt = new Date().toISOString()
    if (item && !item.read_at) {
      item.read_at = optimisticAt
      unread.value = Math.max(0, unread.value - 1)
    }
    marking.value.push(id)
    actionError.value = null
    try {
      await request.run()
      if (generation !== epoch) return false
      if (request.state.value !== 'success') {
        actionError.value = request.error.value
        if (item?.read_at === optimisticAt) {
          item.read_at = null
          unread.value++
        }
        return false
      }
      void refresh()
      return true
    } finally {
      mutations.delete(request.cancel)
      if (generation === epoch) marking.value = marking.value.filter((value) => value !== id)
    }
  }
  async function markAllRead(): Promise<boolean> {
    if (markingAll.value || marking.value.length) return false
    const generation = epoch
    ++revision
    listRequest.cancel()
    const request = useRequest(
      async ({ signal, timeoutMs }) =>
        (
          await api.post('/notifications/read-all', undefined, {
            signal,
            timeout: timeoutMs,
          })
        ).data as unknown,
      { timeoutMs: timeouts.task },
    )
    mutations.add(request.cancel)
    const previousUnread = unread.value
    const changedItems = items.value.filter((n) => !n.read_at)
    const optimisticAt = new Date().toISOString()
    for (const item of changedItems) item.read_at = optimisticAt
    unread.value = 0
    markingAll.value = true
    actionError.value = null
    try {
      await request.run()
      if (generation !== epoch) return false
      if (request.state.value !== 'success') {
        actionError.value = request.error.value
        for (const item of changedItems) if (item.read_at === optimisticAt) item.read_at = null
        unread.value += previousUnread
        return false
      }
      void refresh()
      return true
    } finally {
      mutations.delete(request.cancel)
      if (generation === epoch) markingAll.value = false
    }
  }
  function reset(): void {
    epoch++
    revision++
    listRequest.data.value = undefined
    listRequest.error.value = null
    listRequest.state.value = 'idle'
    clearTimeout(timer)
    listRequest.cancel()
    for (const cancel of mutations) cancel()
    mutations.clear()
    items.value = []
    unread.value = 0
    hints.clear()
    actionError.value = null
    marking.value = []
    markingAll.value = false
  }
  return {
    items,
    unread,
    loading,
    actionError,
    marking,
    markingAll,
    listRequest,
    refresh,
    incoming,
    markRead,
    markAllRead,
    reset,
  }
})
