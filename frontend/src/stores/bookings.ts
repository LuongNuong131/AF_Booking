import { ref, shallowRef } from 'vue'
import { patchBooking } from '../utils/patchBooking'
import { readStorage, writeStorage } from '../utils/storage'
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
  NoteSaveResponse,
  InvoiceResult,
} from '../types/api.generated'
import { timeouts } from '../config/timeouts'

type Params = Record<string, string | number | boolean>
export const useBookingsStore = defineStore('bookings', () => {
  const statuses = shallowRef<Status[]>([])
  const homeKey = ref('')
  let epoch = 0,
    sessionEpoch = 0,
    catalogueAt = 0
  let catalogueEpoch = 0
  const cache = new Map<string, { at: number; value: unknown }>()
  const listeners = new Set<(event: BookingUpdatedData) => void>()
  const versions = new Map<string, number>()
  const pending = new Map<string, { work: Promise<unknown>; signal: AbortSignal }>()
  const cacheKey = (path: string, params: Params) =>
    JSON.stringify([path, Object.entries(params).sort(([a], [b]) => a.localeCompare(b))])
  const clone = <T>(value: T): T => structuredClone(value)
  async function get<T>(
    context: RequestContext,
    path: string,
    params: Params,
    force = false,
  ): Promise<T> {
    const key = cacheKey(path, params)
    const saved = cache.get(key)
    if (!force && saved && Date.now() - saved.at < timeouts.bookingCache) {
      cache.delete(key)
      cache.set(key, saved)
      return clone(saved.value as T)
    }
    const flying = pending.get(key)
    if (flying && !flying.signal.aborted) return clone((await flying.work) as T)
    const generation = epoch
    const work = api
      .get<T>(path, {
        params,
        signal: context.signal,
        timeout: context.timeoutMs,
      })
      .then((r) => r.data)
    pending.set(key, { work, signal: context.signal })
    let result: T
    try {
      result = await work
    } finally {
      if (pending.get(key)?.work === work) pending.delete(key)
    }
    if (generation === epoch && !context.signal.aborted) {
      cache.set(key, { at: Date.now(), value: clone(result) })
      while (cache.size > 50) cache.delete(cache.keys().next().value!)
    }
    return result
  }
  const peekLookup = (key: string) => {
    const saved = cache.get(cacheKey('/bookings/lookup', { key }))
    if (!saved) return null
    cache.delete(cacheKey('/bookings/lookup', { key }))
    cache.set(cacheKey('/bookings/lookup', { key }), saved)
    return { data: clone(saved.value as BookingLookup), fetchedAt: saved.at }
  }
  const lookup = (ctx: RequestContext, key: string, force = false) =>
    get<BookingLookup>(ctx, '/bookings/lookup', { key }, force)
  const list = (
    ctx: RequestContext,
    path: '/bookings' | '/bookings/mine' | '/bookings/stale',
    params: Params,
    force = false,
  ) => get<Page<BookingItem>>(ctx, path, params, force)
  // Visible lists write back their reconciled rows after realtime hydration.
  // A return navigation can reuse that page without another page query.
  function rememberList(path: string, params: Params, page: Page<BookingItem>) {
    cache.set(cacheKey(path, params), {
      at: Date.now(),
      value: JSON.parse(JSON.stringify(page)),
    })
    while (cache.size > 50) cache.delete(cache.keys().next().value!)
  }
  async function catalogue(ctx: RequestContext, force = false) {
    if (!force && statuses.value.length && Date.now() - catalogueAt < timeouts.catalogueCache)
      return statuses.value
    const generation = sessionEpoch
    const stamp = catalogueEpoch
    let saved: { etag?: string; items?: Status[] } = {}
    try {
      saved = JSON.parse(readStorage('localStorage', 'booking.statuses.v1') ?? '{}')
    } catch {
      /* cache miss */
    }
    if (
      !statuses.value.length &&
      Array.isArray(saved.items) &&
      saved.items.every((s) => typeof s.code === 'string' && typeof s.is_done === 'boolean')
    )
      statuses.value = saved.items
    const response = await api.get<Status[]>('/statuses', {
      signal: ctx.signal,
      timeout: ctx.timeoutMs,
      headers: saved.etag ? { 'If-None-Match': saved.etag } : {},
      validateStatus: (status) => status === 200 || status === 304,
    })
    const result = response.status === 304 ? statuses.value : response.data
    if (generation === sessionEpoch && stamp === catalogueEpoch && !ctx.signal.aborted) {
      statuses.value = result
      catalogueAt = Date.now()
      writeStorage(
        'localStorage',
        'booking.statuses.v1',
        JSON.stringify({
          etag: response.headers?.etag ?? saved.etag,
          items: result,
        }),
      )
    }
    return result
  }
  function invalidate() {
    epoch++
    cache.clear()
    pending.clear()
  }
  function invalidateCatalogue() {
    catalogueEpoch++
    catalogueAt = 0
    invalidate()
  }
  function observe(event: BookingUpdatedData) {
    if ((versions.get(event.booking_key) ?? 0) >= event.version) return
    versions.delete(event.booking_key)
    versions.set(event.booking_key, event.version)
    while (versions.size > 2000) versions.delete(versions.keys().next().value!)
    epoch++
    for (const [cacheId, saved] of cache) {
      const lookupValue = saved.value as BookingLookup
      if (
        lookupValue.resolution?.key === event.booking_key &&
        lookupValue.snapshot &&
        lookupValue.snapshot.version < event.version
      ) {
        saved.value = {
          ...lookupValue,
          version: event.version,
          snapshot: patchBooking(lookupValue.snapshot, event, statuses.value),
        }
        saved.at = 0 // display patched snapshot immediately; refresh note history in background
      } else if (!lookupValue.resolution) cache.delete(cacheId)
    }
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
  function committed(result: NoteSaveResponse | InvoiceResult) {
    const row = item(result.snapshot)
    observe({
      booking_key: row.booking_key,
      display_key: row.display_key,
      cw_number: row.cw_number,
      station_code: row.station_code,
      version: row.version,
      invoice_state: row.invoice_state,
      invoice_count: row.invoice_count,
      change_kind: 'note' in result ? 'note' : 'invoice',
      last_agent_id: row.last_agent?.id ?? null,
      last_agent_name: row.last_agent?.full_name ?? null,
      status_code: row.last_status?.code ?? null,
      position: row.last_position,
      updated_at: row.updated_at,
      is_done: row.is_done,
    })
    const cacheId = cacheKey('/bookings/lookup', { key: row.booking_key })
    const saved = cache.get(cacheId)?.value as BookingLookup | undefined
    if (saved && saved.version <= row.version)
      cache.set(cacheId, {
        at: Date.now(),
        value: {
          ...saved,
          snapshot: row,
          exists: true,
          version: row.version,
          group_exists: true,
          group: {
            cw_number: row.cw_number,
            station_code: row.station_code,
            supplier_name: row.supplier.name,
            supplier_type: row.supplier.type,
          },
          invoices: result.invoices ?? saved.invoices,
          history:
            'note' in result
              ? {
                  ...saved.history,
                  items: [
                    result.note,
                    ...saved.history.items.filter((n) => n.id !== result.note.id),
                  ],
                }
              : saved.history,
        },
      })
  }
  return {
    statuses,
    homeKey,
    get,
    peekLookup,
    committed,
    lookup,
    list,
    rememberList,
    catalogue,
    invalidate,
    invalidateCatalogue,
    observe,
    subscribe,
    reset,
    item,
  }
})
