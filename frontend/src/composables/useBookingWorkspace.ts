import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { useOnline } from '@vueuse/core'
import { api } from '../api/client'
import { useRequest } from './useRequest'
import { useViewRefresh } from './useViewRefresh'
import { useBookingsStore } from '../stores/bookings'
import { useRealtimeStore } from '../stores/realtime'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { timeouts } from '../config/timeouts'
import {
  parseBookingKey,
  build_key,
  formatBookingKey,
  normalizeBookingKey,
} from '../utils/bookingKey'
import { draftStorage } from '../utils/bookingDrafts'
import { i18n } from '../i18n'
import type {
  BookingLookup,
  Note,
  CursorPage,
  NoteSaveRequest,
  NoteSaveResponse,
  SupplierType,
} from '../types/api.generated'

export function useBookingWorkspace() {
  const bookings = useBookingsStore(),
    realtime = useRealtimeStore(),
    auth = useAuthStore(),
    ui = useUiStore()
  const input = ref(''),
    key = ref<string | null>(null),
    current = shallowRef<BookingLookup | null>(null)
  const resolution = shallowRef<BookingLookup | null>(null),
    notes = ref<Note[]>([]),
    cursor = ref<string | null>(null)
  const statusCode = ref(''),
    note = ref(''),
    supplierName = ref(''),
    supplierType = ref<SupplierType>('hotel')
  const validation = ref(''),
    draftRestored = ref(false),
    hasDraft = ref(false),
    hasUpdate = ref(false),
    conflict = ref(false)
  const invoiceText = ref(''),
    noInvoice = ref(false)
  const draftFailed = ref(false),
    draftPending = ref(false)
  const online = useOnline()
  let lookupInput = '',
    disposed = false
  let generation = 0,
    draftTimer: ReturnType<typeof setTimeout> | undefined
  let restoringDraft = false
  let attempt: { signature: string; id: string } | null = null
  const draft = draftStorage(auth.user!.id)
  const lookupRequest = useRequest(
    (ctx, value: string, force: boolean = false) => bookings.lookup(ctx, value, force),
    { timeoutMs: timeouts.lookup, retry: true },
  )
  const historyRequest = useRequest(
    async ({ signal, timeoutMs }, value: string, next: string) =>
      (
        await api.get<CursorPage<Note>>(`/bookings/${value}/notes`, {
          params: { cursor: next, limit: 20 },
          signal,
          timeout: timeoutMs,
        })
      ).data,
    { timeoutMs: timeouts.list, retry: true },
  )
  const statusRequest = useRequest(
    (ctx, force: boolean = false) => bookings.catalogue(ctx, force),
    { timeoutMs: timeouts.list, retry: true },
  )
  const saveRequest = useRequest(
    async ({ signal, timeoutMs }, value: string, payload: NoteSaveRequest) =>
      (
        await api.post<NoteSaveResponse>(`/bookings/${value}/notes`, payload, {
          signal,
          timeout: timeoutMs,
        })
      ).data,
    { timeoutMs: timeouts.noteSave },
  )
  const conflictRequest = useRequest((ctx, value: string) => bookings.lookup(ctx, value, true), {
    timeoutMs: timeouts.lookup,
    retry: true,
  })
  const snapshot = computed(() => current.value?.snapshot ?? null)
  const selectedStatus = computed(() => bookings.statuses.find((s) => s.code === statusCode.value))
  const inputMatches = computed(() => {
    const parsed = parseBookingKey(input.value)
    return !!parsed && 'key' in parsed && parsed.key === key.value
  })
  const needsSupplier = computed(() => !!current.value && !current.value.group_exists)
  const invoiceNumbers = computed(() => [
    ...new Set(
      invoiceText.value
        .trim()
        .split(/[\s,]+/)
        .filter(Boolean)
        .map((value) => value.toUpperCase()),
    ),
  ])
  const invalidInvoice = computed(
    () => invoiceNumbers.value.find((value) => !/^[A-Z0-9_./-]{3,40}$/.test(value)) || '',
  )
  const needsInvoice = computed(
    () =>
      !!selectedStatus.value?.invoice_required &&
      (!snapshot.value || snapshot.value.invoice_state === 'unknown'),
  )
  const invoiceValid = computed(() =>
    noInvoice.value
      ? !invoiceNumbers.value.length
      : !!invoiceNumbers.value.length &&
        invoiceNumbers.value.every((value) => /^[A-Z0-9_./-]{3,40}$/.test(value)),
  )
  const showInvoice = computed(
    () => needsInvoice.value || !!invoiceText.value.trim() || noInvoice.value,
  )
  const canSave = computed(
    () =>
      !!key.value &&
      inputMatches.value &&
      online.value &&
      !!selectedStatus.value &&
      (!selectedStatus.value.note_required || !!note.value.trim()) &&
      (!needsSupplier.value || !!supplierName.value.trim()) &&
      (!showInvoice.value || invoiceValid.value) &&
      !saveRequest.pending.value &&
      !conflict.value,
  )

  function flushDraft() {
    clearTimeout(draftTimer)
    if (!key.value) return
    draftFailed.value = !draft.save(
      key.value,
      statusCode.value,
      note.value,
      invoiceText.value,
      noInvoice.value,
    )
    draftPending.value = false
    hasDraft.value = !!statusCode.value || !!note.value || !!invoiceText.value || noInvoice.value
  }
  watch(
    [statusCode, note, invoiceText, noInvoice],
    () => {
      if (restoringDraft || !key.value) return
      clearTimeout(draftTimer)
      draftPending.value = true
      draftTimer = setTimeout(flushDraft, timeouts.draftDebounce)
    },
    { flush: 'sync' },
  )
  function restoreDraft(value: string) {
    restoringDraft = true
    const saved = draft.get(value)
    statusCode.value = saved?.status_code ?? ''
    note.value = saved?.note ?? ''
    invoiceText.value = saved?.invoice_text ?? ''
    noInvoice.value = saved?.no_invoice ?? false
    draftRestored.value = !!saved
    hasDraft.value = !!saved
    restoringDraft = false
  }
  function discardDraft() {
    clearTimeout(draftTimer)
    if (key.value) draftFailed.value = !draft.discard(key.value)
    draftPending.value = false
    restoringDraft = true
    statusCode.value = ''
    note.value = ''
    invoiceText.value = ''
    noInvoice.value = false
    restoringDraft = false
    hasDraft.value = false
    draftRestored.value = false
    attempt = null
  }
  function engage() {
    if (key.value && inputMatches.value) realtime.acquire(key.value)
  }
  function newerRemote(value: string, version: number) {
    const update = realtime.bookingUpdates.get(value)
    return !!update && update.version > version && update.last_agent_id !== auth.user?.id
  }
  function accept(result: BookingLookup) {
    const value = result.resolution.key
    if (!value) return
    key.value = value
    input.value = formatBookingKey(value)
    bookings.homeKey = value
    current.value = result
    resolution.value = null
    notes.value = result.history.items
    cursor.value = result.history.next_cursor
    supplierName.value = result.group?.supplier_name ?? ''
    supplierType.value = result.group?.supplier_type ?? 'hotel'
    hasUpdate.value = newerRemote(value, result.version)
    restoreDraft(value)
    engage()
  }
  function normalizeInput() {
    const parsed = parseBookingKey(input.value)
    if (parsed && 'key' in parsed) input.value = parsed.display_key
  }
  watch(input, (value) => {
    if (lookupInput && normalizeBookingKey(value) !== normalizeBookingKey(lookupInput)) {
      resolution.value = null
      if (lookupRequest.pending.value) {
        generation++
        lookupRequest.cancel()
      }
    }
    if (!saveRequest.pending.value) {
      if (!value.trim() && (key.value || lookupInput)) clear()
      else if (!inputMatches.value) realtime.release()
      else if (key.value && realtime.activeBookingKey !== key.value) engage()
    }
  })
  async function open(value = input.value) {
    if (disposed) return
    if (saveRequest.pending.value) {
      validation.value = i18n.global.t('bookingUi.waitForSave')
      return
    }
    const parsed = parseBookingKey(value)
    if (!parsed) {
      validation.value = i18n.global.t('invalid_key')
      return
    }
    flushDraft()
    realtime.release()
    historyRequest.cancel()
    conflictRequest.cancel()
    const ticket = ++generation
    key.value = null
    current.value = null
    resolution.value = null
    notes.value = []
    cursor.value = null
    restoringDraft = true
    statusCode.value = ''
    note.value = ''
    invoiceText.value = ''
    noInvoice.value = false
    restoringDraft = false
    hasDraft.value = false
    draftRestored.value = false
    hasUpdate.value = false
    conflict.value = false
    conflictRequest.data.value = undefined
    saveRequest.error.value = null
    saveRequest.state.value = 'idle'
    validation.value = ''
    attempt = null
    input.value = 'key' in parsed ? parsed.display_key : formatBookingKey(parsed.normalized)
    lookupInput = input.value
    const result = await lookupRequest.run('key' in parsed ? parsed.key : parsed.normalized)
    if (!result || ticket !== generation) return
    if (result.resolution.status === 'exact') accept(result)
    else resolution.value = result
  }
  function acceptResolved() {
    if (resolution.value?.resolution.status === 'resolved_from_partial') accept(resolution.value)
  }
  async function applyStation(station: string) {
    const parsed = parseBookingKey(input.value)
    if (!parsed || 'key' in parsed || !/^[A-Z]{3}$/.test(station)) return
    await open(build_key(parsed.cw_number, station, parsed.period))
  }
  async function refresh() {
    if (disposed) return
    if (!key.value || saveRequest.pending.value) return
    const ticket = generation,
      value = key.value
    lookupInput = input.value
    const result = await lookupRequest.run(value, true)
    if (result && ticket === generation && value === key.value) {
      current.value = result
      notes.value = result.history.items
      cursor.value = result.history.next_cursor
      hasUpdate.value = newerRemote(value, result.version)
    }
  }
  async function loadMore() {
    if (disposed) return
    if (!key.value || !cursor.value || historyRequest.pending.value) return
    const value = key.value,
      next = cursor.value,
      ticket = generation
    const result = await historyRequest.run(value, next)
    if (!result || value !== key.value || ticket !== generation) return
    const ids = new Set(notes.value.map((n) => n.id))
    notes.value = [...notes.value, ...result.items.filter((n) => !ids.has(n.id))]
    cursor.value = result.next_cursor
  }
  async function loadConflict() {
    if (key.value) {
      conflictRequest.data.value = undefined
      await conflictRequest.run(key.value)
    }
  }
  function reviewConflict() {
    const result = conflictRequest.data.value
    if (!result || result.booking_key !== key.value) return
    current.value = result
    notes.value = result.history.items
    cursor.value = result.history.next_cursor
    conflict.value = false
    hasUpdate.value = key.value ? newerRemote(key.value, result.version) : false
    attempt = null
  }
  async function save(): Promise<boolean> {
    if (disposed || !canSave.value || !key.value) return false
    const value = key.value,
      ticket = generation
    const submittedStatus = statusCode.value,
      submittedNote = note.value,
      submittedInvoice = invoiceText.value,
      submittedNoInvoice = noInvoice.value
    const payloadBase = {
      status_code: submittedStatus,
      note: submittedNote.trim() || null,
      expected_version: current.value?.version ?? 0,
      ...(showInvoice.value
        ? { invoices: noInvoice.value ? { no_invoice: true } : { add: invoiceNumbers.value } }
        : {}),
      ...(!current.value?.exists ? { confirm_new: true } : {}),
      ...(needsSupplier.value
        ? { supplier_name: supplierName.value.trim(), supplier_type: supplierType.value }
        : {}),
    }
    const signature = JSON.stringify([value, payloadBase])
    if (attempt?.signature !== signature) attempt = { signature, id: crypto.randomUUID() }
    flushDraft()
    const result = await saveRequest.run(value, { ...payloadBase, client_request_id: attempt.id })
    if (!result || ticket !== generation || key.value !== value) {
      if (
        ticket === generation &&
        ['STATUS_INACTIVE', 'NOTE_REQUIRED', 'INVOICE_REQUIRED'].includes(
          saveRequest.error.value?.code ?? '',
        )
      )
        void statusRequest.run(true)
      if (saveRequest.error.value?.code === 'VERSION_CONFLICT' && ticket === generation) {
        attempt = null
        conflict.value = true
        void loadConflict()
      }
      return false
    }
    const item = bookings.item(result.snapshot)
    if ((current.value?.version ?? 0) <= result.snapshot.version) {
      current.value = {
        ...current.value!,
        exists: true,
        group_exists: true,
        group: {
          cw_number: item.cw_number,
          station_code: item.station_code,
          supplier_name: item.supplier_name,
          supplier_type: item.supplier_type,
        },
        snapshot: item,
        version: item.version,
        done_warning: null,
      }
    }
    notes.value = [result.note, ...notes.value.filter((n) => n.id !== result.note.id)].sort(
      (a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id,
    )
    if (
      statusCode.value === submittedStatus &&
      note.value === submittedNote &&
      invoiceText.value === submittedInvoice &&
      noInvoice.value === submittedNoInvoice
    )
      discardDraft()
    else flushDraft() // New typing during the request is a new draft, not part of the saved note.
    attempt = null
    realtime.release()
    bookings.invalidate()
    if (item.last_agent && item.last_status)
      bookings.observe({
        booking_key: item.booking_key,
        display_key: item.display_key,
        cw_number: item.cw_number,
        station_code: item.station_code,
        version: item.version,
        last_agent_id: item.last_agent.id,
        last_agent_name: item.last_agent.full_name,
        status_code: item.last_status.code,
        position: item.last_position ?? '',
        updated_at: item.updated_at,
        is_done: item.is_done,
      })
    ui.notify(i18n.global.t('bookingUi.saved'), 'success')
    return true
  }
  function clear() {
    if (saveRequest.pending.value) {
      validation.value = i18n.global.t('bookingUi.waitForSave')
      return
    }
    flushDraft()
    generation++
    lookupRequest.cancel()
    historyRequest.cancel()
    conflictRequest.cancel()
    realtime.release()
    lookupInput = ''
    key.value = null
    current.value = null
    resolution.value = null
    input.value = ''
    notes.value = []
    cursor.value = null
    restoringDraft = true
    statusCode.value = ''
    note.value = ''
    invoiceText.value = ''
    noInvoice.value = false
    restoringDraft = false
    validation.value = ''
    hasDraft.value = false
    draftRestored.value = false
    hasUpdate.value = false
    bookings.homeKey = ''
    attempt = null
    saveRequest.error.value = null
    saveRequest.state.value = 'idle'
  }
  const unsubscribe = bookings.subscribe((event) => {
    if (
      event.booking_key === key.value &&
      event.version > (current.value?.version ?? 0) &&
      event.last_agent_id !== auth.user?.id
    )
      hasUpdate.value = true
  })
  useViewRefresh(refresh)
  onScopeDispose(() => {
    disposed = true
    flushDraft()
    generation++
    realtime.release()
    unsubscribe()
  })
  return {
    input,
    key,
    current,
    snapshot,
    resolution,
    notes,
    cursor,
    statusCode,
    note,
    supplierName,
    supplierType,
    needsSupplier,
    validation,
    draftRestored,
    hasDraft,
    hasUpdate,
    conflict,
    online,
    selectedStatus,
    inputMatches,
    canSave,
    draftFailed,
    draftPending,
    invoiceText,
    noInvoice,
    invoiceNumbers,
    needsInvoice,
    showInvoice,
    invoiceValid,
    invalidInvoice,
    lookupRequest,
    historyRequest,
    statusRequest,
    saveRequest,
    conflictRequest,
    open,
    normalizeInput,
    acceptResolved,
    applyStation,
    refresh,
    loadMore,
    loadConflict,
    reviewConflict,
    save,
    clear,
    discardDraft,
    engage,
  }
}
