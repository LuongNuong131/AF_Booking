import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api/client'
import { useAuthStore } from './auth'
import { useBookingsStore } from './bookings'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import { readStorage, writeStorage } from '../utils/storage'
import { parseBookingKey } from '../utils/bookingKey'
import { loadImages, removeImages, imageBatchKey } from '../utils/imageOutbox'
import type { RequestFailure } from '../api/errors'
import type {
  Attachment,
  BookingLookup,
  BookingItem,
  Note,
  NoteSaveRequest,
  NoteSaveResponse,
  InvoiceResult,
  Invoice,
  InvoiceChange,
} from '../types/api.generated'

export type OutgoingResult = NoteSaveResponse | InvoiceResult
export interface OutgoingNote {
  operation?: 'note' | 'invoice'
  invoices?: Invoice[]
  hasImages?: boolean
  savedNote?: NoteSaveResponse
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
  const listeners = new Set<(entry: OutgoingNote, result: OutgoingResult | null) => void>()
  const request = useRequest(
    async ({ signal, timeoutMs }, entry: OutgoingNote): Promise<OutgoingResult> => {
      if (entry.operation === 'invoice') return (await api.put<InvoiceResult>(
        `/bookings/${entry.key}/invoices`, entry.payload.invoices, { signal, timeout: timeoutMs },
      )).data
      const batchKey = imageBatchKey(entry.note.agent.id, entry.id)
      const files = entry.hasImages ? await loadImages(batchKey) : []
      if (signal.aborted) throw signal.reason
      if (entry.hasImages && !files) throw new Error('Selected images are missing from browser storage. Retry from the original browser.')
      const result = entry.savedNote ?? (await api.post<NoteSaveResponse>(`/bookings/${entry.key}/notes`, entry.payload, {
        signal, timeout: timeouts.noteSave,
      })).data
      if (signal.aborted) throw signal.reason
      if (entry.hasImages) {
        entry.savedNote = result
        changed()
        for (const file of files ?? []) {
          const image = (await api.post<Attachment>(`/notes/${result.note.id}/attachments`, file, {
            params: { file_name: file.name }, headers: { 'Content-Type': file.type }, signal, timeout: timeouts.noteSave,
          })).data
          if (!result.note.attachments.some(a => a.id === image.id)) result.note.attachments.push(image)
        }
      }
      return result
    },
    { timeoutMs: 6 * timeouts.noteSave },
  )
  const storageKey = () => `booking.outbox.v1.${owner}`
  function persist(): boolean {
    if (corrupt) return false
    const ok =
      owner !== null &&
      writeStorage('localStorage', storageKey(), JSON.stringify(entries.value))
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
            (value.operation === undefined || ['note', 'invoice'].includes(value.operation)) &&
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
  function enqueue(
    base: BookingLookup,
    payload: NoteSaveRequest,
    operation: 'note' | 'invoice' = 'note',
    hasImages = false,
  ): OutgoingNote | null {
    if (
      !auth.user ||
      owner !== auth.user.id ||
      entries.value.length >= 50 ||
      !base.resolution.key
    )
      return null
    const status = bookings.statuses.find((s) => s.code === payload.status_code)
    const parsed = parseBookingKey(base.resolution.key)
    if ((!status && operation !== 'invoice') || !parsed || !('key' in parsed)) return null
    const selectedStatus = status ?? {
      code: base.snapshot?.last_status?.code ?? 'BUNDLE',
      label: base.snapshot?.last_status?.label ?? 'Bundle',
      position_label: base.snapshot?.last_position ?? '',
      is_done: base.snapshot?.is_done ?? false,
    }
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
          Date.UTC(
            2000 + Number(parsed.period.slice(0, 2)),
            Number(parsed.period.slice(2)) - 1,
            1,
          ),
        ),
      ),
      supplier,
      supplier_name: supplier.name,
      supplier_type: supplier.type,
      version: base.version,
      last_status: { code: selectedStatus.code, label: selectedStatus.label },
      last_position: selectedStatus.position_label,
      last_agent: user,
      last_note_preview: payload.note?.slice(0, 255) ?? null,
      is_done: selectedStatus.is_done,
      done_at: selectedStatus.is_done ? at : null,
      updated_at: at,
      is_stale: false,
      invoice_state: base.snapshot?.invoice_state ?? 'unknown',
      invoice_count: base.snapshot?.invoice_count ?? 0,
      invoices_preview: base.snapshot?.invoices_preview ?? [],
      stale_hours: null,
      my_pending_tasks: (base.my_tasks ?? []).length,
    }
    if (operation === 'invoice' && base.snapshot) Object.assign(preview, base.snapshot)
    let invoices = [...(base.invoices ?? [])]
    if (payload.invoices) {
      invoices = invoices.filter((i) => !payload.invoices!.remove_ids?.includes(i.id))
      for (const number of payload.invoices.add ?? [])
        if (!invoices.some((i) => i.invoice_number === number))
          invoices.unshift({
            id: -Date.now() - invoices.length,
            invoice_number: number,
            added_by: user,
            created_at: at,
          })
      preview.invoice_count = invoices.length
      preview.invoice_state = invoices.length
        ? 'has_invoice'
        : payload.invoices.no_invoice
          ? 'no_invoice'
          : 'unknown'
      preview.invoices_preview = invoices.slice(0, 3).map((i) => i.invoice_number)
    }
    const entry: OutgoingNote = {
      operation,
      hasImages,
      invoices,
      id: payload.client_request_id,
      key: parsed.key,
      payload: JSON.parse(JSON.stringify(payload)),
      base: JSON.parse(
        JSON.stringify({
          ...base,
          history: { items: [], next_cursor: null },
        }),
      ),
      preview,
      note: {
        id: -Date.now() - entries.value.length,
        agent: user,
        status: { code: selectedStatus.code, label: selectedStatus.label },
        position: selectedStatus.position_label,
        note: payload.note ?? null,
        created_at: at,
        attachments: [],
        invoice_change: payload.invoices
          ? {
              added: payload.invoices.add ?? [],
              removed: (base.invoices ?? [])
                .filter((i) => payload.invoices?.remove_ids?.includes(i.id))
                .map((i) => i.invoice_number),
              no_invoice: payload.invoices.no_invoice ?? null,
            }
          : null,
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
      complete(entry, result)
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
        if (!entry.savedNote) for (const listener of listeners) listener(entry, null)
      }
      changed()
    }
    void flush()
  }
  function complete(entry: OutgoingNote, result: OutgoingResult) {
    entries.value = entries.value.filter((e) => e.id !== entry.id)
    const next = entries.value.find((e) => e.key === entry.key)
    if (next && next.attempts === 0) next.payload.expected_version = result.snapshot.version
    changed()
    if (entry.hasImages) void removeImages(imageBatchKey(entry.note.agent.id, entry.id)).catch(() => undefined)
    bookings.committed(result)
    for (const listener of listeners) listener(entry, result)
  }
  function finishWithoutImages(id: string) {
    const entry = entries.value.find(e => e.id === id)
    if (!entry?.savedNote || entry.state === 'sending') return
    complete(entry, entry.savedNote)
    void flush()
  }
  function retry(id?: string) {
    for (const entry of entries.value)
      if ((!id || entry.id === id) && (entry.state !== 'blocked' || entry.savedNote)) {
        entry.nextAt = 0
        if (entry.savedNote) entry.state = 'queued'
      }
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
  function subscribe(listener: (entry: OutgoingNote, result: OutgoingResult | null) => void) {
    listeners.add(listener)
    return () => listeners.delete(listener)
  }
  return {
    entries,
    enqueueInvoices: (base: BookingLookup, invoices: InvoiceChange) =>
      enqueue(
        base,
        {
          note: null,
          status_code: base.snapshot?.last_status?.code ?? 'BUNDLE',
          expected_version: base.version,
          client_request_id: crypto.randomUUID(),
          invoices,
        },
        'invoice',
      ),
    reviewId,
    count,
    storageError,
    request,
    enqueue,
    start,
    stop,
    retry,
    finishWithoutImages,
    flush,
    take,
    subscribe,
  }
})
