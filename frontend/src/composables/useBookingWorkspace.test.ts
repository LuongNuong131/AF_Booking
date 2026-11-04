import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'
import { api } from '../api/client'
import { useOutboxStore } from '../stores/outbox'
import { useAuthStore } from '../stores/auth'
import { useBookingsStore } from '../stores/bookings'
import { useRealtimeStore } from '../stores/realtime'
import { useBookingWorkspace } from './useBookingWorkspace'
import { draftStorage } from '../utils/bookingDrafts'
import { event, KEY, lookup, saved, statuses, user } from '../test/bookingFixtures'
let scope: EffectScope
beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  sessionStorage.clear()
  const auth = useAuthStore()
  auth.user = user
  auth.token = 'test-only'
  auth.ready = true
  useBookingsStore().statuses = structuredClone(statuses)
  useOutboxStore().start(user.id)
  scope = effectScope()
})
afterEach(() => {
  scope.stop()
  useOutboxStore().stop()
  vi.restoreAllMocks()
  vi.useRealTimers()
})
const setup = () => scope.run(() => useBookingWorkspace())!
function apiFailure(code: string, status = 409) {
  const config = {
    method: 'post',
    headers: new AxiosHeaders(),
  } as InternalAxiosRequestConfig
  return new AxiosError('Test', '', config, undefined, {
    status,
    statusText: '',
    headers: {},
    config,
    data: { code, message: code, details: lookup(2).snapshot },
  })
}
it('normalizes input and sends canonical lookup/save keys with the loaded version', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue({ data: lookup() })
  const post = vi.spyOn(api, 'post').mockResolvedValue({ data: saved() })
  const w = setup()
  await w.open('cw 2154654 - rdu - 2609')
  expect(get).toHaveBeenCalledWith(
    '/bookings/lookup',
    expect.objectContaining({ params: { key: KEY } }),
  )
  expect(w.input.value).toBe('CW 2154654-RDU-2609')
  w.statusCode.value = 'BUNDLE'
  w.note.value = 'My update'
  expect(await w.save()).toBe(true)
  expect(post).toHaveBeenCalledWith(
    `/bookings/${KEY}/notes`,
    expect.objectContaining({
      expected_version: 1,
      status_code: 'BUNDLE',
      note: 'My update',
      client_request_id: expect.any(String),
    }),
    expect.any(Object),
  )
  await vi.waitFor(() => expect(w.notes.value.map((n) => n.id)).toEqual([2, 1]))
  expect(w.note.value).toBe('')
  expect(useRealtimeStore().activeBookingKey).toBeNull()
})
it('applies a partial-key suggestion without another request', async () => {
  const result = lookup()
  result.resolution = {
    ...result.resolution,
    status: 'resolved_from_partial',
    input_kind: 'partial',
  }
  const get = vi.spyOn(api, 'get').mockResolvedValue({ data: result })
  const w = setup()
  await w.open('CW 2154654-2609')
  expect(w.key.value).toBeNull()
  expect(w.canSave.value).toBe(false)
  w.acceptResolved()
  expect(w.key.value).toBe(KEY)
  expect(w.notes.value).toHaveLength(1)
  expect(get).toHaveBeenCalledTimes(1)
})
it('requires a station and Supplier before saving a brand new CW', async () => {
  const partial = {
    ...lookup(),
    exists: false,
    snapshot: null,
    group: null,
    group_exists: false,
    booking_key: null,
    resolution: {
      status: 'needs_station',
      input_kind: 'partial',
      key: null,
      display_key: null,
    },
    history: { items: [], next_cursor: null },
  }
  const full = {
    ...lookup(0),
    exists: false,
    snapshot: null,
    group: null,
    group_exists: false,
    history: { items: [], next_cursor: null },
  }
  const get = vi
    .spyOn(api, 'get')
    .mockResolvedValueOnce({ data: partial })
    .mockResolvedValueOnce({ data: full })
  const w = setup()
  await w.open('CW2154654-2609')
  w.statusCode.value = 'BUNDLE'
  expect(w.canSave.value).toBe(false)
  await w.applyStation('RDU')
  expect(get.mock.calls[1]?.[1]?.params).toEqual({ key: KEY })
  w.statusCode.value = 'BUNDLE'
  expect(w.canSave.value).toBe(false)
  w.supplierName.value = ' AB '
  expect(w.canSave.value).toBe(false)
  w.supplierName.value = 'New Hotel'
  expect(w.canSave.value).toBe(false)
  w.newConfirmed.value = true
  expect(w.canSave.value).toBe(true)
})
it('keeps a draft on foreign realtime updates and refreshes without replacing the note', async () => {
  vi.spyOn(api, 'get')
    .mockResolvedValueOnce({ data: lookup() })
    .mockResolvedValueOnce({ data: lookup(2) })
  const w = setup()
  await w.open(KEY)
  w.statusCode.value = 'BUNDLE'
  w.note.value = 'Keep this draft'
  useBookingsStore().observe(event())
  expect(w.hasUpdate.value).toBe(true)
  expect(w.current.value?.version).toBe(1)
  expect(w.note.value).toBe('Keep this draft')
  await w.refresh()
  expect(w.current.value?.version).toBe(2)
  expect(w.note.value).toBe('Keep this draft')
})
it('blocks saving a key whose station differs from the known supplier folder', async () => {
  const result = lookup()
  result.group = { ...result.group!, station_code: 'YUL' }
  vi.spyOn(api, 'get').mockResolvedValue({ data: result })
  const post = vi.spyOn(api, 'post'),
    w = setup()
  await w.open(KEY)
  w.statusCode.value = 'BUNDLE'
  expect(w.canSave.value).toBe(false)
  expect(await w.save()).toBe(false)
  expect(post).not.toHaveBeenCalled()
})
it('reuses the exact request UUID on an uncertain manual retry and blocks duplicate saves', async () => {
  vi.spyOn(api, 'get').mockResolvedValue({ data: lookup() })
  const config = {
    method: 'post',
    headers: new AxiosHeaders(),
  } as InternalAxiosRequestConfig
  const post = vi
    .spyOn(api, 'post')
    .mockRejectedValueOnce(new AxiosError('timeout', 'ECONNABORTED', config))
    .mockResolvedValueOnce({ data: saved() })
  const w = setup()
  await w.open(KEY)
  w.statusCode.value = 'BUNDLE'
  w.note.value = 'Same operation'
  expect(await w.save()).toBe(true)
  await vi.waitFor(() => expect(useOutboxStore().entries[0]?.state).toBe('retrying'))
  useOutboxStore().retry()
  await vi.waitFor(() => expect(useOutboxStore().count).toBe(0))
  expect(post.mock.calls[0]?.[1]).toEqual(post.mock.calls[1]?.[1])
  expect(post).toHaveBeenCalledTimes(2)
})
it('409 requires review, preserves text, then uses a new version and UUID', async () => {
  vi.spyOn(api, 'get')
    .mockResolvedValueOnce({ data: lookup() })
    .mockResolvedValueOnce({ data: lookup(2) })
  const post = vi
    .spyOn(api, 'post')
    .mockRejectedValueOnce(apiFailure('VERSION_CONFLICT'))
    .mockResolvedValueOnce({ data: saved(3) })
  const w = setup()
  await w.open(KEY)
  w.statusCode.value = 'BUNDLE'
  w.note.value = 'Review me'
  expect(await w.save()).toBe(true)
  await vi.waitFor(() => expect(w.conflict.value).toBe(true))
  await vi.waitFor(() => expect(w.conflictRequest.data.value?.version).toBe(2))
  expect(w.current.value?.version).toBe(1)
  expect(w.canSave.value).toBe(false)
  w.reviewConflict()
  expect(w.note.value).toBe('Review me')
  expect(w.current.value?.version).toBe(2)
  await w.save()
  await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(2))
  expect(post.mock.calls[1]?.[1]).toMatchObject({ expected_version: 2 })
  expect((post.mock.calls[1]?.[1] as { client_request_id: string }).client_request_id).not.toBe(
    (post.mock.calls[0]?.[1] as { client_request_id: string }).client_request_id,
  )
})
it('retains new typing during an in-flight save and cancels stale lookup results', async () => {
  vi.spyOn(api, 'get').mockResolvedValue({ data: lookup() })
  let finish!: (value: unknown) => void
  vi.spyOn(api, 'post').mockImplementation(
    () =>
      new Promise((done) => {
        finish = done
      }),
  )
  const w = setup()
  await w.open(KEY)
  w.statusCode.value = 'BUNDLE'
  w.note.value = 'First'
  const first = w.save()
  await Promise.resolve()
  expect(await w.save()).toBe(false)
  w.note.value = 'Typing while saving'
  finish({ data: saved() })
  await first
  await vi.waitFor(() => expect(useOutboxStore().count).toBe(0))
  w.engage()
  await new Promise((resolve) => setTimeout(resolve, 510))
  expect(w.note.value).toBe('Typing while saving')
  expect(draftStorage(3).get(KEY)?.note).toBe('Typing while saving')
})
it('persists after 500ms, restores per user and clears a saved/discarded draft', async () => {
  vi.useFakeTimers()
  vi.spyOn(api, 'get').mockResolvedValue({ data: lookup() })
  const w = setup()
  await w.open(KEY)
  w.statusCode.value = 'REJECTION'
  w.note.value = 'Draft text'
  expect(draftStorage(3).get(KEY)).toBeNull()
  await vi.advanceTimersByTimeAsync(500)
  expect(draftStorage(3).get(KEY)?.note).toBe('Draft text')
  expect(draftStorage(5).get(KEY)).toBeNull()
  await w.open(KEY)
  expect(w.note.value).toBe('Draft text')
  expect(w.draftRestored.value).toBe(true)
  w.discardDraft()
  expect(draftStorage(3).get(KEY)).toBeNull()
})
it('expires drafts after 7 days and enforces note/invoice requirements without inventing a declaration', async () => {
  vi.useFakeTimers()
  draftStorage(3).save(KEY, 'BUNDLE', 'Old')
  await vi.advanceTimersByTimeAsync(7 * 24 * 60 * 60 * 1000 + 1)
  expect(draftStorage(3).get(KEY)).toBeNull()
  vi.spyOn(api, 'get').mockResolvedValue({ data: lookup() })
  const w = setup()
  await w.open(KEY)
  w.statusCode.value = 'REJECTION'
  expect(w.canSave.value).toBe(false)
  w.note.value = 'Required'
  expect(w.canSave.value).toBe(true)
  w.statusCode.value = 'DONE'
  expect(w.needsInvoice.value).toBe(true)
  expect(w.canSave.value).toBe(false)
  w.noInvoice.value = true
  expect(w.canSave.value).toBe(true)
  w.invoiceText.value = 'INV-123'
  expect(w.canSave.value).toBe(false)
  w.noInvoice.value = false
  expect(w.canSave.value).toBe(true)
})

it('loads history in batches of 20 and merges duplicate cursor rows by id', async () => {
  const first = lookup()
  first.history.next_cursor = 'cursor-1'
  const get = vi
    .spyOn(api, 'get')
    .mockResolvedValueOnce({ data: first })
    .mockResolvedValueOnce({
      data: { items: [first.history.items[0]], next_cursor: null },
    })
  const w = setup()
  await w.open(KEY)
  await w.loadMore()
  expect(get).toHaveBeenCalledWith(
    `/bookings/${KEY}/notes`,
    expect.objectContaining({ params: { cursor: 'cursor-1', limit: 20 } }),
  )
  expect(w.notes.value).toHaveLength(1)
  expect(w.cursor.value).toBeNull()
})

it('ignores an older lookup and releases a lease when the input is cleared', async () => {
  let finish!: (value: unknown) => void
  vi.spyOn(api, 'get')
    .mockImplementationOnce(
      () =>
        new Promise((done) => {
          finish = done
        }),
    )
    .mockResolvedValue({ data: lookup(2) })
  const w = setup(),
    older = w.open(KEY)
  await Promise.resolve()
  const newer = w.open(KEY)
  await newer
  finish({ data: lookup() })
  await older
  expect(w.current.value?.version).toBe(2)
  expect(useRealtimeStore().activeBookingKey).toBe(KEY)
  w.input.value = ''
  await Promise.resolve()
  expect(useRealtimeStore().activeBookingKey).toBeNull()
  expect(w.key.value).toBeNull()
})

it('keeps new input typed during lookup and discards the superseded resolution', async () => {
  let finish!: (value: unknown) => void
  vi.spyOn(api, 'get').mockImplementation(
    () =>
      new Promise((done) => {
        finish = done
      }),
  )
  const w = setup(),
    opening = w.open(KEY)
  await Promise.resolve()
  w.input.value = 'CW9999999-YUL-2610'
  await Promise.resolve()
  finish({ data: lookup() })
  await opening
  expect(w.input.value).toBe('CW9999999-YUL-2610')
  expect(w.key.value).toBeNull()
  expect(w.lookupRequest.pending.value).toBe(false)
})

it('reports a real storage failure without losing the in-memory note', async () => {
  vi.spyOn(api, 'get').mockResolvedValue({ data: lookup() })
  const w = setup()
  await w.open(KEY)
  w.statusCode.value = 'BUNDLE'
  w.note.value = 'Keep me'
  vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
    throw new Error('Storage unavailable')
  })
  w.saveRequest.cancel()
  scope.stop()
  expect(w.draftFailed.value).toBe(true)
  expect(w.note.value).toBe('Keep me')
})

it('does not resurrect a moderated note from an older committed UUID replay', async () => {
  vi.spyOn(api, 'get')
    .mockResolvedValueOnce({ data: lookup() })
    .mockResolvedValue({ data: lookup(3) })
  let finish!: (value: unknown) => void
  vi.spyOn(api, 'post').mockImplementation(
    () =>
      new Promise((done) => {
        finish = done
      }),
  )
  const w = setup()
  await w.open(KEY)
  w.statusCode.value = 'BUNDLE'
  w.note.value = 'Originally committed'
  expect(await w.save()).toBe(true)
  await w.refresh()
  expect(w.current.value?.version).toBe(3)
  finish({ data: saved(2) })
  await vi.waitFor(() => expect(useOutboxStore().count).toBe(0))
  expect(w.notes.value.map((n) => n.id)).toEqual([3])
  expect(w.current.value?.version).toBe(3)
})

it('restores a duplicate note for confirmation and sends only an explicit override', async () => {
  vi.spyOn(api, 'get').mockResolvedValue({ data: lookup() })
  const config = { method: 'post', headers: new AxiosHeaders() } as InternalAxiosRequestConfig
  const post = vi
    .spyOn(api, 'post')
    .mockRejectedValueOnce(
      new AxiosError('Duplicate', '', config, undefined, {
        status: 409,
        statusText: '',
        headers: {},
        config,
        data: {
          code: 'DUPLICATE_RECENT_NOTE',
          message: 'Duplicate',
          details: { note: saved(1).note, seconds: 4 },
        },
      }),
    )
    .mockResolvedValueOnce({ data: saved(2) })
  const w = setup()
  await w.open(KEY)
  w.statusCode.value = 'BUNDLE'
  w.note.value = 'Repeated message'
  expect(await w.save()).toBe(true)
  await vi.waitFor(() => expect(w.duplicate.value).toBe(true))
  expect(w.note.value).toBe('Repeated message')
  expect(w.duplicateSeconds.value).toBe(4)
  expect(post).toHaveBeenCalledTimes(1)
  w.duplicate.value = false
  expect(await w.save(true)).toBe(true)
  await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(2))
  expect(post.mock.calls[1]?.[1]).toMatchObject({ allow_duplicate: true, note: 'Repeated message' })
  expect((post.mock.calls[1]?.[1] as { client_request_id: string }).client_request_id).not.toBe(
    (post.mock.calls[0]?.[1] as { client_request_id: string }).client_request_id,
  )
})

it('persists assignment fields with the draft and durable note payload', async () => {
  vi.useFakeTimers()
  vi.spyOn(api, 'get').mockResolvedValue({ data: lookup() })
  const w = setup()
  await w.open(KEY)
  w.statusCode.value = 'BUNDLE'
  w.note.value = 'Ask for supplier follow-up'
  w.assignTo.value = 5
  w.assignMessage.value = 'Please check tomorrow'
  await vi.advanceTimersByTimeAsync(600)
  expect(draftStorage(3).get(KEY)).toMatchObject({
    assign_to: 5,
    assign_message: 'Please check tomorrow',
  })
  const enqueue = vi.spyOn(useOutboxStore(), 'enqueue').mockReturnValue(null)
  await w.save()
  expect(enqueue).toHaveBeenCalledWith(
    expect.anything(),
    expect.objectContaining({ assign_to: 5, assign_message: 'Please check tomorrow' }),
  )
})
