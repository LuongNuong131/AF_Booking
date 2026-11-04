import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { useAuthStore } from './auth'
import { useUiStore } from './ui'
import { errorMessage } from '../api/request-error'
import { timeouts } from '../config/timeouts'
import type { WatchState } from '../types/api.generated'

export const useCollaborationStore = defineStore('collaboration', () => {
  const watched = ref<Record<string, boolean>>({}),
    pending = ref<string[]>([]),
    assignedCount = ref(0),
    revision = ref(0)
  const owned = new Set<() => void>(),
    auth = useAuthStore(),
    ui = useUiStore()
  const touched = new Map<string, number>()
  const versions = new Map<string, number>()
  const countRequest = useRequest(
    async ({ signal, timeoutMs }) =>
      (
        await api.get<{ total: number }>('/assignments', {
          params: { view: 'to_me', status: 'open', size: 1 },
          signal,
          timeout: timeoutMs,
        })
      ).data,
    { timeoutMs: timeouts.list },
  )
  function seed(key: string, value: boolean) {
    if (!(key in watched.value)) watched.value = { ...watched.value, [key]: value }
  }
  async function toggle(key: string, current?: boolean) {
    if (pending.value.includes(key)) return false
    touched.set(key, Date.now())
    versions.set(key, (versions.get(key) ?? 0) + 1)
    const generation = auth.epoch
    pending.value.push(key)
    const request = useRequest(
      async ({ signal, timeoutMs }) => {
        let previous = watched.value[key] ?? current
        if (previous === undefined) {
          const result = await api.get<{
            snapshot: { my_watching: boolean } | null
          }>(`/bookings/lookup`, {
            params: { key },
            signal,
            timeout: timeoutMs,
          })
          previous = result.data.snapshot?.my_watching ?? false
        }
        return (
          await api.request<WatchState>({
            url: `/bookings/${key}/watch`,
            method: previous ? 'DELETE' : 'PUT',
            signal,
            timeout: timeoutMs,
          })
        ).data
      },
      { timeoutMs: timeouts.task },
    )
    owned.add(request.cancel)
    try {
      const result = await request.run()
      if (generation !== auth.epoch) return false
      if (result) {
        watched.value = { ...watched.value, [key]: result.watching }
        revision.value++
        return true
      }
      if (request.error.value) ui.notify(errorMessage(request.error.value), 'error')
      return false
    } finally {
      owned.delete(request.cancel)
      if (generation === auth.epoch) {
        versions.set(key, (versions.get(key) ?? 0) + 1)
        pending.value = pending.value.filter((k) => k !== key)
      }
    }
  }
  async function acceptNote(
    key: string,
    watching: boolean | undefined,
    queuedAt: string,
    retried: boolean,
  ) {
    if (watching === undefined) return
    if (
      !retried &&
      !pending.value.includes(key) &&
      (touched.get(key) ?? 0) < Date.parse(queuedAt)
    ) {
      watched.value = { ...watched.value, [key]: watching }
      return
    }
    // UUID replay retains its original response, which may predate a later watch
    // change. Reconcile that private flag instead of rolling the user's choice back.
    const epoch = auth.epoch,
      version = versions.get(key)
    const request = useRequest(
      async ({ signal, timeoutMs }) =>
        (
          await api.get<{ snapshot: { my_watching: boolean } | null }>('/bookings/lookup', {
            params: { key },
            signal,
            timeout: timeoutMs,
          })
        ).data,
      { timeoutMs: timeouts.lookup },
    )
    owned.add(request.cancel)
    try {
      const result = await request.run()
      if (
        result?.snapshot &&
        epoch === auth.epoch &&
        version === versions.get(key) &&
        !pending.value.includes(key)
      )
        watched.value = { ...watched.value, [key]: result.snapshot.my_watching }
    } finally {
      owned.delete(request.cancel)
    }
  }
  async function refreshCount() {
    const epoch = auth.epoch,
      result = await countRequest.run()
    if (result && epoch === auth.epoch) assignedCount.value = result.total
  }
  function changed() {
    revision.value++
    void refreshCount()
  }
  function reset() {
    touched.clear()
    versions.clear()
    for (const cancel of owned) cancel()
    owned.clear()
    countRequest.cancel()
    watched.value = {}
    pending.value = []
    assignedCount.value = 0
    revision.value++
  }
  return {
    watched,
    pending,
    assignedCount,
    revision,
    seed,
    toggle,
    acceptNote,
    refreshCount,
    changed,
    reset,
  }
})
