import { folderKey } from '../utils/folderKey'
import { computed, onScopeDispose, ref } from 'vue'
import { useFoldersStore } from '../stores/folders'
import { useRequest } from './useRequest'
import { useViewRefresh } from './useViewRefresh'
import { timeouts } from '../config/timeouts'
import { classifyQuery } from '../utils/searchQuery'
import { normalizeBookingKey, parseBookingKey } from '../utils/bookingKey'
import type { BookingLookup } from '../types/api.generated'

interface Workspace {
  input: string
  key: string | null
  current: BookingLookup | null
  resolution: BookingLookup | null
  validation: string
  saveRequest: { pending: boolean }
  lookupRequest: { pending: boolean; cancel: () => void }
  open: (value?: string) => Promise<void>
  clear: () => void
  acceptResolved: () => void
}
export function useSmartSearch(w: Workspace, opened: (key: string) => void) {
  const store = useFoldersStore(),
    level = ref<'root' | 'folder' | 'booking'>('root'),
    query = ref(''),
    page = ref(1),
    cw = ref<string | null>(null)
  let timer: ReturnType<typeof setTimeout> | undefined,
    disposed = false,
    pendingKey = '',
    opening: Promise<boolean> | null = null
  let lastOpened = '',
    lastOpenedAt = 0
  const request = useRequest(
    (ctx, q: string, p: number, force: boolean = false) => store.readSearch(ctx, q, p, force),
    { timeoutMs: timeouts.search, retry: true },
  )
  const result = computed(() => (query.value ? store.search(query.value, page.value) : null))
  const station = computed(() =>
    result.value?.kind === 'station' || result.value?.kind === 'station_period'
      ? result.value.station.code
      : null,
  )
  const folderName = computed(() =>
    cw.value
      ? (store.detail(cw.value)?.folder.supplier_name ??
        (w.current?.group && folderKey(w.current.group) === cw.value ? w.current.group.supplier_name : ''))
      : '',
  )
  function stop() {
    clearTimeout(timer)
    request.cancel()
  }
  async function search(force = false) {
    if (disposed || !query.value || w.saveRequest.pending) return
    const response = await request.run(query.value, page.value, force)
    if (!response || disposed) return
    // The server's discriminator remains authoritative, including future aliases.
    if (response.kind === 'booking') await openBooking(response.booking_key, false)
    else if (response.kind === 'partial_key') await openBooking(response.query, false)
  }
  function markOpened() {
    if (w.key) {
      if (w.current?.group_exists && w.current.group) cw.value = folderKey(w.current.group)
      opened(w.key)
    }
  }
  async function openBooking(value: string, keepContext = false): Promise<boolean> {
    if (w.saveRequest.pending) return false
    if (!parseBookingKey(value)) {
      stop()
      w.clear()
      w.input = value
      query.value = ''
      cw.value = null
      level.value = 'booking'
      await w.open(value)
      return false
    }
    const normalized = normalizeBookingKey(value)
    if (opening && pendingKey === normalized) return opening
    stop()
    level.value = 'booking'
    if (!keepContext) {
      query.value = ''
      cw.value = null
      page.value = 1
    }
    pendingKey = normalized
    const active = (async () => {
      await w.open(value)
      if (disposed || level.value !== 'booking' || pendingKey !== normalized) return false
      markOpened()
      lastOpened = normalized
      lastOpenedAt = Date.now()
      return !!w.key
    })()
    opening = active
    try {
      return await active
    } finally {
      if (opening === active) {
        opening = null
        pendingKey = ''
      }
    }
  }
  function typed() {
    const classified = classifyQuery(w.input)
    if (opening && pendingKey === normalizeBookingKey(w.input)) return
    stop()
    w.lookupRequest.cancel()
    w.validation = ''
    if (classified.kind === 'full_key' || classified.kind === 'partial_key') {
      timer = setTimeout(() => void openBooking(w.input), 150)
      return
    }
    if (classified.kind === 'none' && w.input.trim()) {
      level.value = 'booking'
      void openBooking(w.input)
      return
    }
    level.value = 'root'
    cw.value = null
    query.value = classified.query
    page.value = 1
    if (query.value)
      timer = setTimeout(() => {
        void search()
      }, timeouts.smartSearchDebounce)
  }
  async function submit() {
    clearTimeout(timer)
    const parsed = parseBookingKey(w.input)
    if (parsed) {
      if (opening && pendingKey === normalizeBookingKey(w.input)) {
        await opening
        return
      }
      if (w.resolution?.resolution.status === 'resolved_from_partial') {
        w.acceptResolved()
        markOpened()
        return
      }
      if (
        lastOpened === normalizeBookingKey(w.input) &&
        Date.now() - lastOpenedAt < 10000 &&
        (w.key || w.resolution)
      )
        return
      await openBooking(w.input, false)
      return
    }
    if (level.value === 'root' && result.value?.kind === 'folder' && !request.pending.value) {
      openFolder(folderKey(result.value.folder))
      return
    }
    if (w.input.trim()) {
      query.value = classifyQuery(w.input).query
      level.value = 'root'
      await search()
    }
  }
  function openFolder(value: string) {
    if (w.saveRequest.pending) return
    stop()
    w.clear()
    cw.value = value
    level.value = 'folder'
  }
  function back() {
    if (w.saveRequest.pending) return
    stop()
    if (level.value === 'booking' && cw.value) {
      w.clear()
      level.value = 'folder'
      return
    }
    if (level.value === 'folder') {
      w.clear()
      cw.value = null
      level.value = 'root'
      w.input = query.value
      if (query.value) void search()
      return
    }
    root()
  }
  function root() {
    if (w.saveRequest.pending) return
    stop()
    w.clear()
    cw.value = null
    query.value = ''
    page.value = 1
    level.value = 'root'
  }
  function stationRoot() {
    if (w.saveRequest.pending) return
    stop()
    w.clear()
    cw.value = null
    level.value = 'root'
    w.input = query.value
    if (query.value) void search()
  }
  function changePage(value: number) {
    if (w.saveRequest.pending) return
    stop()
    page.value = value
    void search()
  }
  useViewRefresh(() => {
    if (level.value === 'root' && query.value) void search(true)
  })
  onScopeDispose(() => {
    disposed = true
    stop()
  })
  return {
    level,
    query,
    page,
    cw,
    result,
    station,
    folderName,
    request,
    typed,
    submit,
    search,
    openBooking,
    openFolder,
    back,
    root,
    stationRoot,
    changePage,
  }
}
