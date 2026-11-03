import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { RequestContext } from '../composables/useRequest'
import type {
  BookingLookup,
  BookingItem,
  BookingSnapshot,
  BookingUpdatedData,
  Page,
  Status,
} from '../types/api.generated'
import { timeouts } from '../config/timeouts'

type Params = Record<string, string | number | boolean>
export const useBookingsStore = defineStore('bookings', () => {
  const statuses = ref<Status[]>([])
  const homeKey = ref('')
  let epoch = 0,
    sessionEpoch = 0,
    catalogueAt = 0
  const cache = new Map<string, { at: number; value: unknown }>()
  const listeners = new Set<(event: BookingUpdatedData) => void>()
  const versions = new Map<string, number>()
  const clone = <T>(value: T): T => structuredClone(value)
  async function get<T>(
    context: RequestContext,
    path: string,
    params: Params,
    force = false,
  ): Promise<T> {
    const key = JSON.stringify([
      path,
      Object.entries(params).sort(([a], [b]) => a.localeCompare(b)),
    ])
    const saved = cache.get(key)
    if (!force && saved && Date.now() - saved.at < timeouts.bookingCache)
      return clone(saved.value as T)
    const generation = epoch
    const result = (
      await api.get<T>(path, { params, signal: context.signal, timeout: context.timeoutMs })
    ).data
    if (generation === epoch && !context.signal.aborted) {
      cache.set(key, { at: Date.now(), value: clone(result) })
      while (cache.size > 50) cache.delete(cache.keys().next().value!)
    }
    return result
  }
  const lookup = (ctx: RequestContext, key: string, force = false) =>
    get<BookingLookup>(ctx, '/bookings/lookup', { key }, force)
  const list = (
    ctx: RequestContext,
    path: '/bookings' | '/bookings/mine' | '/bookings/stale',
    params: Params,
    force = false,
  ) => get<Page<BookingItem>>(ctx, path, params, force)
  async function catalogue(ctx: RequestContext, force = false) {
    if (!force && statuses.value.length && Date.now() - catalogueAt < timeouts.catalogueCache)
      return statuses.value
    const generation = sessionEpoch
    const result = await get<Status[]>(ctx, '/statuses', {}, force)
    if (generation === sessionEpoch && !ctx.signal.aborted) {
      statuses.value = result
      catalogueAt = Date.now()
    }
    return result
  }
  function invalidate() {
    epoch++
    cache.clear()
  }
  function observe(event: BookingUpdatedData) {
    if ((versions.get(event.booking_key) ?? 0) >= event.version) return
    versions.delete(event.booking_key)
    versions.set(event.booking_key, event.version)
    while (versions.size > 2000) versions.delete(versions.keys().next().value!)
    invalidate()
    for (const listener of listeners) listener(event)
  }
  function subscribe(listener: (event: BookingUpdatedData) => void) {
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  }
  function reset() {
    sessionEpoch++
    invalidate()
    statuses.value = []
    catalogueAt = 0
    versions.clear()
    homeKey.value = ''
  }
  function item(snapshot: BookingSnapshot): BookingItem {
    return {
      ...snapshot,
      supplier_name: snapshot.supplier.name,
      supplier_type: snapshot.supplier.type,
    }
  }
  return {
    statuses,
    homeKey,
    get,
    lookup,
    list,
    catalogue,
    invalidate,
    observe,
    subscribe,
    reset,
    item,
  }
})
