import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api/client'
import { useAuthStore } from './auth'
import { useBookingsStore } from './bookings'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import { readStorage, writeStorage } from '../utils/storage'
import { parseBookingKey } from '../utils/bookingKey'
import type { RequestFailure } from '../api/errors'
import type {
  BookingLookup,
  BookingItem,
  Note,
  NoteSaveRequest,
  NoteSaveResponse,
} from '../types/api.generated'

export interface OutgoingNote {
  id: string
  key: string
  payload: NoteSaveRequest
  base: BookingLookup
  preview: BookingItem
  note: Note
  state: 'queued' | 'sending' | 'retrying' | 'blocked'
  attempts: number
  nextAt: number
  error: RequestFailure | null
}
export const transientSaveFailure = (error: RequestFailure) =>
  !!error.network ||
  error.status === 429 ||
  (error.status ?? 0) >= 500 ||
  ['REQUEST_TIMEOUT', 'SERVICE_BUSY'].includes(error.code)
const delays = [2000, 5000, 15000, 30000]

export const useOutboxStore = defineStore('outbox', () => {
  const auth = useAuthStore(),
    bookings = useBookingsStore()
  const entries = shallowRef<OutgoingNote[]>([]),
    storageError = ref(false)
  const reviewId = ref<string | null>(null)
  const count = computed(() => entries.value.length)
  let corrupt = false
  let owner: number | null = null,
    epoch = 0,
    running = false,
    stopped = true
  let timer: ReturnType<typeof setTimeout> | undefined
  const listeners = new Set<(entry: OutgoingNote, result: NoteSaveResponse | null) => void>()
  const request = useRequest(
    async ({ signal, timeoutMs }, entry: OutgoingNote) =>
      (
        await api.post<NoteSaveResponse>(`/bookings/${entry.key}/notes`, entry.payload, {
          signal,
          timeout: timeoutMs,
        })
      ).data,
    { timeoutMs: timeouts.noteSave },
  )
  const storageKey = () => `booking.outbox.v1.${owner}`
  function persist(): boolean {
    if (corrupt) return false
    const ok =
      owner !== null && writeStorage('localStorage', storageKey(), JSON.stringify(entries.value))
    storageError.value = !ok
    return ok
  }
  function changed() {
    entries.value = [...entries.value]
    persist()
  }
  function stop() {
    stopped = true
    epoch++
    clearTimeout(timer)
    request.cancel()
    running = false
    for (const entry of entries.value) if (entry.state === 'sending') entry.state = 'queued'
    if (owner !== null) changed()
    entries.value = []
    owner = null
  }
  function start(userId: number) {
    if (owner === userId && !stopped) return
    stop()
    owner = userId
    corrupt = false
    storageError.value = false
    stopped = false
    try {
      const saved: unknown = JSON.parse(readStorage('localStorage', storageKey()) ?? '[]')
      if (!Array.isArray(saved) || saved.length > 50) throw new Error('Invalid outbox')
      entries.value = saved
        .filter((value): value is OutgoingNote => {
          const parsed = parseBookingKey(value?.key ?? '')
          return (
            !!parsed &&
            'key' in parsed &&
            parsed.key === value.key &&
            typeof value.id === 'string' &&
            /^[0-9a-f-]{36}$/i.test(value.id) &&
            value.payload?.client_request_id === value.id &&
            typeof value.payload?.status_code === 'string' &&
            typeof value.payload.expected_version === 'number' &&
            value.base?.resolution?.key === value.key &&
            value.preview?.booking_key === value.key &&
            value.note?.agent?.id === userId &&
            ['queued', 'sending', 'retrying', 'blocked'].includes(value.state)
          )
        })
        .map((entry) => ({
          ...entry,
          state: entry.state === 'sending' ? 'queued' : entry.state,
        }))
      if (entries.value.length !== saved.length) throw new Error('Invalid outbox item')
    } catch {
      corrupt = true
      entries.value = []
      storageError.value = true
    }
    void flush()
  }
  function enqueue(base: BookingLookup, payload: NoteSaveRequest): OutgoingNote | null {
    if (!auth.user || owner !== auth.user.id || entries.value.length >= 50 || !base.resolution.key)
      return null
    const status = bookings.statuses.find((s) => s.code === payload.status_code)
    const parsed = parseBookingKey(base.resolution.key)
    if (!status || !parsed || !('key' in parsed)) return null
    const at = new Date().toISOString(),
      user = { id: auth.user.id, full_name: auth.user.full_name }
    const supplier = {
      name: base.group?.supplier_name ?? payload.supplier_name ?? '',
      type: base.group?.supplier_type ?? payload.supplier_type ?? 'hotel',
    }
    const preview: BookingItem = {
      ...(base.snapshot ?? {}),
      booking_key: parsed.key,
      display_key: parsed.display_key,
      cw_number: parsed.cw_number,
      station_code: parsed.station_code,
      period: parsed.period,
      period_label: new Intl.DateTimeFormat('en-US', {
        month: 'short',
        year: 'numeric',
        timeZone: 'UTC',
      }).format(
        new Date(
          Date.UTC(2000 + Number(parsed.period.slice(0, 2)), Number(parsed.period.slice(2)) - 1, 1),
        ),
      ),
      supplier,
      supplier_name: supplier.name,
      supplier_type: supplier.type,
      version: base.version,
      last_status: { code: status.code, label: status.label },
      last_position: status.position_label,
      last_agent: user,
      last_note_preview: payload.note?.slice(0, 255) ?? null,
      is_done: status.is_done,
      done_at: status.is_done ? at : null,
      updated_at: at,
      is_stale: false,
      invoice_state: base.snapshot?.invoice_state ?? 'unknown',
      invoice_count: base.snapshot?.invoice_count ?? 0,
      invoices_preview: base.snapshot?.invoices_preview ?? [],
      stale_hours: null,
      my_pending_tasks: (base.my_tasks ?? []).length,
    }
    const entry: OutgoingNote = {
      id: payload.client_request_id,
      key: parsed.key,
      payload: structuredClone(payload),
      base: structuredClone({
        ...base,
        history: { items: [], next_cursor: null },
      }),
      preview,
      note: {
        id: -Date.now() - entries.value.length,
        agent: user,
        status: { code: status.code, label: status.label },
        position: status.position_label,
        note: payload.note ?? null,
        created_at: at,
        attachments: [],
        invoice_change: null,
      },
      state: 'queued',
      attempts: 0,
      nextAt: 0,
      error: null,
    }
    entries.value = [...entries.value, entry]
    // Persistence is a prerequisite for clearing the user's form.
    if (!persist()) {
      entries.value = entries.value.filter((e) => e.id !== entry.id)
      return null
    }
    void flush()
    return entry
  }
  async function flush() {
    clearTimeout(timer)
    if (stopped || running || !auth.isAuthenticated || navigator.onLine === false) return
    const generation = epoch
    const firstByKey = new Map<string, OutgoingNote>()
    for (const entry of entries.value)
      if (!firstByKey.has(entry.key)) firstByKey.set(entry.key, entry)
    const eligible = [...firstByKey.values()].filter((e) => e.state !== 'blocked')
    const entry = eligible.find((e) => e.nextAt <= Date.now())
    if (!entry) {
      if (eligible.length)
        timer = setTimeout(
          () => void flush(),
          Math.max(1, Math.min(...eligible.map((e) => e.nextAt)) - Date.now()),
        )
      return
    }
    running = true
    entry.state = 'sending'
    entry.attempts++
    changed()
    const result = await request.run(entry)
    if (generation !== epoch || stopped) return
    running = false
    if (result) {
      entries.value = entries.value.filter((e) => e.id !== entry.id)
      const next = entries.value.find((e) => e.key === entry.key)
      if (next && next.attempts === 0) next.payload.expected_version = result.snapshot.version
      changed()
      bookings.committed(result)
      for (const listener of listeners) listener(entry, result)
    } else {
      entry.error = request.error.value ?? {
        code: 'REQUEST_TIMEOUT',
        message: '',
      }
      if (transientSaveFailure(entry.error)) {
        entry.state = 'retrying'
        entry.nextAt =
          Date.now() +
          Math.max(
            entry.error.retryAfterMs ?? 0,
            delays[Math.min(entry.attempts - 1, delays.length - 1)]!,
          )
      } else {
        entry.state = 'blocked'
        for (const listener of listeners) listener(entry, null)
      }
      changed()
    }
    void flush()
  }
  function retry(id?: string) {
    for (const entry of entries.value)
      if ((!id || entry.id === id) && entry.state !== 'blocked') entry.nextAt = 0
    changed()
    void flush()
  }
  function take(id: string): OutgoingNote | undefined {
    const entry = entries.value.find((e) => e.id === id && e.state === 'blocked')
    if (entry) {
      entries.value = entries.value.filter((e) => e.id !== id)
      changed()
      void flush()
    }
    return entry
  }
  function subscribe(listener: (entry: OutgoingNote, result: NoteSaveResponse | null) => void) {
    listeners.add(listener)
    return () => listeners.delete(listener)
  }
  return {
    entries,
    reviewId,
    count,
    storageError,
    request,
    enqueue,
    start,
    stop,
    retry,
    flush,
    take,
    subscribe,
  }
})
