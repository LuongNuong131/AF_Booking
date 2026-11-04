import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api/client'
import { useRequest, type RequestContext } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import { useBookingsStore } from './bookings'
import { parseBookingKey } from '../utils/bookingKey'
import { normalizeSearch } from '../utils/searchQuery'
import type {
  BookingUpdatedData,
  FolderCard,
  FolderDetail,
  GroupInfo,
  MonthRow,
  Page,
  SearchResponse,
} from '../types/api.generated'

type Value = SearchResponse | FolderDetail | Page<FolderCard>
type Entry = { value: Value; at: number }
type Params = Record<string, string | number>
const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T
const identity = (path: string, params: Params = {}) =>
  JSON.stringify([path, Object.entries(params).sort(([a], [b]) => a.localeCompare(b))])
export const useFoldersStore = defineStore('folders', () => {
  const cache = ref(new Map<string, Entry>()),
    recent = ref<FolderCard[]>([])
  const liveError = ref(false)
  const listeners = new Set<(cw: string, card: FolderCard) => void>()
  let epoch = 0,
    revision = 0,
    owner: number | null = null,
    running = 0
  const interests = new Map<string, number>(),
    timers = new Map<string, ReturnType<typeof setTimeout>>()
  const queue = new Set<string>(),
    active = new Set<() => void>()
  const searchId = (q: string, page = 1) =>
    identity('/search', { q: normalizeSearch(q), page, size: 20 })
  const folderId = (cw: string) => identity(`/folders/${cw}`)
  const pageId = (params: Params) => identity('/folders', params)
  const peek = <T extends Value>(key: string): T | null =>
    (cache.value.get(key)?.value as T | undefined) ?? null
  const search = (q: string, page = 1) => peek<SearchResponse>(searchId(q, page))
  const detail = (cw: string) => peek<FolderDetail>(folderId(cw))
  const page = (params: Params) => peek<Page<FolderCard>>(pageId(params))
  function put(key: string, value: Value) {
    cache.value.delete(key)
    cache.value.set(key, { value: copy(value), at: Date.now() })
    while (cache.value.size > 50) cache.value.delete(cache.value.keys().next().value!)
  }
  async function read<T extends Value>(
    ctx: RequestContext,
    path: string,
    params: Params = {},
    force = false,
  ): Promise<T> {
    const key = identity(path, params),
      saved = cache.value.get(key),
      generation = epoch
    if (!force && saved && Date.now() - saved.at < timeouts.folderCache) {
      cache.value.delete(key)
      cache.value.set(key, saved)
      return copy(saved.value as T)
    }
    for (let retry = 0; retry < 2; retry++) {
      const stamp = revision
      const value = (
        await api.get<T>(path, {
          params,
          signal: ctx.signal,
          timeout: ctx.timeoutMs,
        })
      ).data
      if (ctx.signal.aborted || generation !== epoch)
        throw new DOMException('Cancelled', 'AbortError')
      if (stamp !== revision) {
        if (!retry) continue
        throw new Error('Data changed during this request. Retry.')
      }
      put(key, value)
      if ('kind' in value && value.kind === 'folder')
        put(folderId(value.folder.cw_number), {
          folder: value.folder,
          months: value.months,
        })
      return value
    }
    throw new Error('Retry required')
  }
  const readSearch = (ctx: RequestContext, q: string, page = 1, force = false) =>
    read<SearchResponse>(ctx, '/search', { q: normalizeSearch(q), page, size: 20 }, force)
  const readDetail = (ctx: RequestContext, cw: string, force = false) =>
    read<FolderDetail>(ctx, `/folders/${cw}`, {}, force)
  const readPage = (ctx: RequestContext, params: Params, force = false) =>
    read<Page<FolderCard>>(ctx, '/folders', params, force)
  function cards(value: Value): FolderCard[] {
    if ('folder' in value) return [value.folder]
    if ('kind' in value) {
      if (value.kind === 'station') return value.sections.flatMap((s) => s.items)
      if (value.kind === 'folders') return value.items
      return []
    }
    return value.items
  }
  function eachCard(fn: (card: FolderCard) => void) {
    for (const e of cache.value.values()) cards(e.value).forEach(fn)
    recent.value.forEach(fn)
  }
  function remember(cw: string) {
    const value = detail(cw)?.folder
    if (!value) return
    recent.value = [copy(value), ...recent.value.filter((f) => f.cw_number !== cw)].slice(0, 10)
    persistRecent()
  }
  function persistRecent() {
    if (owner)
      try {
        localStorage.setItem(`booking.recent-folders.${owner}`, JSON.stringify(recent.value))
      } catch {
        /* Optional history; current navigation is still available. */
      }
  }
  function patchMonth(row: MonthRow, event: BookingUpdatedData) {
    if (row.booking_key !== event.booking_key) return
    if (event.change_kind === 'invoice') {
      row.invoice_state = (event.invoice_state ??
        row.invoice_state) as MonthRow['invoice_state']
      row.invoice_count = event.invoice_count ?? row.invoice_count
      return
    }
    if (row.updated_at >= event.updated_at) return
    row.last_status = event.status_code
      ? {
          code: event.status_code,
          label:
            useBookingsStore().statuses.find((s) => s.code === event.status_code)?.label ??
            event.status_code,
        }
      : null
    row.last_agent =
      event.last_agent_id && event.last_agent_name
        ? { id: event.last_agent_id, full_name: event.last_agent_name }
        : null
    row.last_position = event.position
    row.updated_at = event.updated_at
    row.is_done = event.is_done
    row.is_stale = false
  }
  function observe(event: BookingUpdatedData) {
    revision++
    const old = detail(event.cw_number)?.months.find((r) => r.booking_key === event.booking_key)
    const wasDone = old?.is_done,
      wasStale = old?.is_stale
    for (const entry of cache.value.values()) {
      entry.at = 0
      if ('months' in entry.value) entry.value.months.forEach((r) => patchMonth(r, event))
      else if ('kind' in entry.value && entry.value.kind === 'station_period')
        entry.value.items.forEach((r) => patchMonth(r, event))
    }
    const parsed = parseBookingKey(event.booking_key)
    eachCard((card) => {
      if (event.change_kind === 'invoice') return
      if (card.cw_number !== event.cw_number || card.last_activity_at > event.updated_at) return
      if (wasDone !== undefined && wasDone !== event.is_done)
        card.open_count = Math.max(0, card.open_count + (event.is_done ? -1 : 1))
      if (wasStale) card.stale_count = Math.max(0, (card.stale_count ?? 0) - 1)
      card.last_activity_at = event.updated_at
      if (
        !card.latest ||
        card.latest.booking_key === event.booking_key ||
        (parsed && parsed.period > (parseBookingKey(card.latest.booking_key)?.period ?? ''))
      )
        card.latest = {
          booking_key: event.booking_key,
          display_key: event.display_key,
          period_label: parsed?.period_label ?? '',
          status: event.status_code
            ? {
                code: event.status_code,
                label:
                  useBookingsStore().statuses.find((s) => s.code === event.status_code)
                    ?.label ?? event.status_code,
              }
            : null,
          agent:
            event.last_agent_id && event.last_agent_name
              ? { id: event.last_agent_id, full_name: event.last_agent_name }
              : null,
        }
    })
    if (interests.has(event.cw_number)) schedule(event.cw_number)
  }
  function schedule(cw: string) {
    clearTimeout(timers.get(cw))
    timers.set(
      cw,
      setTimeout(() => {
        timers.delete(cw)
        queue.add(cw)
        pump()
      }, timeouts.smartSearchDebounce),
    )
  }
  function pump() {
    while (running < 4 && queue.size) {
      const cw = queue.values().next().value!
      queue.delete(cw)
      if (!interests.has(cw)) continue
      running++
      const generation = epoch
      const request = useRequest((ctx) => readDetail(ctx, cw, true), {
        timeoutMs: timeouts.search,
        retry: true,
      })
      active.add(request.cancel)
      void request
        .run()
        .then((result) => {
          if (generation !== epoch) return
          if (result) {
            eachCard((card) => {
              if (card.cw_number === cw) Object.assign(card, result.folder)
            })
            persistRecent()
            listeners.forEach((listener) => listener(cw, result.folder))
            liveError.value = false
          } else liveError.value = true
        })
        .finally(() => {
          active.delete(request.cancel)
          if (generation === epoch) {
            running--
            pump()
          }
        })
    }
  }
  function watchFolder(cw: string) {
    const generation = epoch
    interests.set(cw, (interests.get(cw) ?? 0) + 1)
    return () => {
      if (generation !== epoch) return
      const n = (interests.get(cw) ?? 1) - 1
      if (n) interests.set(cw, n)
      else interests.delete(cw)
    }
  }
  async function rename(
    ctx: RequestContext,
    cw: string,
    body: { supplier_name: string; supplier_type: FolderCard['supplier_type'] },
  ) {
    const generation = epoch
    const group = (
      await api.patch<GroupInfo>(`/folders/${cw}`, body, {
        signal: ctx.signal,
        timeout: ctx.timeoutMs,
      })
    ).data
    if (generation !== epoch || ctx.signal.aborted) return group
    revision++
    for (const entry of cache.value.values()) entry.at = 0
    eachCard((card) => {
      if (card.cw_number === cw) {
        card.supplier_name = group.supplier_name
        card.supplier_type = group.supplier_type
      }
    })
    persistRecent()
    useBookingsStore().invalidate()
    return group
  }
  function reset(userId: number | null = null) {
    epoch++
    revision++
    active.forEach((cancel) => cancel())
    active.clear()
    timers.forEach(clearTimeout)
    timers.clear()
    queue.clear()
    running = 0
    cache.value.clear()
    interests.clear()
    recent.value = []
    liveError.value = false
    owner = userId
    if (owner)
      try {
        const saved: unknown = JSON.parse(
          localStorage.getItem(`booking.recent-folders.${owner}`) ?? '[]',
        )
        if (Array.isArray(saved))
          recent.value = saved
            .filter(
              (r): r is FolderCard =>
                !!r &&
                typeof r === 'object' &&
                /^CW\d{5,10}$/.test(r.cw_number) &&
                typeof r.supplier_name === 'string' &&
                r.supplier_name.length <= 255 &&
                /^[A-Z]{3}$/.test(r.station_code) &&
                ['hotel', 'transportation'].includes(r.supplier_type) &&
                Number.isSafeInteger(r.booking_count) &&
                Number.isSafeInteger(r.open_count) &&
                typeof r.last_activity_at === 'string',
            )
            .slice(0, 10)
            .map((r) => ({ ...r, latest: null, stale_count: 0 }))
      } catch {
        /* Ignore unavailable or invalid optional history. */
      }
  }
  function invalidate() {
    revision++
    for (const entry of cache.value.values()) entry.at = 0
  }
  return {
    subscribe(listener: (cw: string, card: FolderCard) => void) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    invalidate,
    cache,
    recent,
    liveError,
    search,
    detail,
    page,
    readSearch,
    readDetail,
    readPage,
    remember,
    watchFolder,
    rename,
    observe,
    reset,
  }
})
