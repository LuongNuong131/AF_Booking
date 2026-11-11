import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'
import { api } from '../api/client'
import { useAuthStore } from './auth'
import { useBookingsStore } from './bookings'
import { useOutboxStore, transientSaveFailure } from './outbox'
import { KEY, lookup, saved, statuses, user } from '../test/bookingFixtures'
const payload = (text = 'Queued note') => ({
  status_code: 'BUNDLE',
  note: text,
  expected_version: 1,
  client_request_id: crypto.randomUUID(),
})
const settle = async () => {
  for (let i = 0; i < 20; i++) await Promise.resolve()
}
beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.user = user
  auth.token = 'test'
  auth.ready = true
  useBookingsStore().statuses = statuses
  useOutboxStore().start(3)
})
afterEach(() => {
  useOutboxStore().stop()
  vi.restoreAllMocks()
  vi.useRealTimers()
})
it('persists before sending, retries backoff with the exact UUID and replaces the preview', async () => {
  const outbox = useOutboxStore(),
    p = payload()
  const config = {
    method: 'post',
    headers: new AxiosHeaders(),
  } as InternalAxiosRequestConfig
  const post = vi
    .spyOn(api, 'post')
    .mockRejectedValueOnce(new AxiosError('offline', 'ERR_NETWORK', config))
    .mockResolvedValueOnce({ data: saved() })
  const entry = outbox.enqueue(lookup(), p)!
  expect(JSON.parse(localStorage.getItem('booking.outbox.v1.3')!)[0].payload).toEqual(p)
  expect(entry.preview.last_note_preview).toBe('Queued note')
  await settle()
  expect(entry.state).toBe('retrying')
  expect(outbox.request.pending).toBe(false)
  await vi.advanceTimersByTimeAsync(1999)
  expect(post).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(1)
  await settle()
  expect(outbox.count).toBe(0)
  expect(post.mock.calls[0]?.[1]).toEqual(post.mock.calls[1]?.[1])
})
it('holds each booking in order and updates the version only before the first attempt', async () => {
  const outbox = useOutboxStore()
  let finish!: (v: unknown) => void
  const post = vi
    .spyOn(api, 'post')
    .mockImplementationOnce(
      () =>
        new Promise((done) => {
          finish = done
        }),
    )
    .mockResolvedValueOnce({ data: saved(3) })
  outbox.enqueue(lookup(), payload('First'))
  outbox.enqueue(lookup(), payload('Second'))
  await settle()
  expect(post).toHaveBeenCalledTimes(1)
  finish({ data: saved(2) })
  await settle()
  expect(post).toHaveBeenCalledTimes(2)
  expect(post.mock.calls[1]?.[1]).toMatchObject({
    note: 'Second',
    expected_version: 2,
  })
  expect(outbox.count).toBe(0)
})
it('rolls back business failures and never retries them or a following note', async () => {
  const outbox = useOutboxStore(),
    config = {
      method: 'post',
      headers: new AxiosHeaders(),
    } as InternalAxiosRequestConfig
  const post = vi.spyOn(api, 'post').mockRejectedValue(
    new AxiosError('conflict', '', config, undefined, {
      status: 409,
      statusText: '',
      headers: {},
      config,
      data: { code: 'VERSION_CONFLICT', message: 'Review' },
    }),
  )
  const callback = vi.fn()
  outbox.subscribe(callback)
  outbox.enqueue(lookup(), payload())
  outbox.enqueue(lookup(), payload('Next'))
  await settle()
  expect(outbox.entries[0]?.state).toBe('blocked')
  expect(callback).toHaveBeenCalledWith(expect.objectContaining({ key: KEY }), null)
  await vi.advanceTimersByTimeAsync(60000)
  expect(post).toHaveBeenCalledTimes(1)
})
it('survives reload and sends once online; other users cannot load the queue', async () => {
  const outbox = useOutboxStore()
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
  outbox.enqueue(lookup(), payload())
  expect(outbox.count).toBe(1)
  outbox.stop()
  outbox.start(5)
  expect(outbox.count).toBe(0)
  outbox.stop()
  outbox.start(3)
  expect(outbox.count).toBe(1)
  const post = vi.spyOn(api, 'post').mockResolvedValue({ data: saved() })
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
  outbox.retry()
  await settle()
  expect(post).toHaveBeenCalledTimes(1)
  expect(outbox.count).toBe(0)
})
it('refuses a 51st note and refuses to clear a form when storage fails', () => {
  const outbox = useOutboxStore()
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
  for (let i = 0; i < 50; i++) expect(outbox.enqueue(lookup(), payload())).not.toBeNull()
  expect(outbox.enqueue(lookup(), payload())).toBeNull()
  outbox.entries = []
  vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
    throw new Error('quota')
  })
  expect(outbox.enqueue(lookup(), payload())).toBeNull()
  expect(outbox.count).toBe(0)
  expect(outbox.storageError).toBe(true)
})
it.each([
  { code: 'REQUEST_TIMEOUT', message: '' },
  { code: 'SERVICE_BUSY', message: '' },
  { code: 'RATE_LIMITED', message: '', status: 429 },
])('treats timeout/busy/rate limiting as temporary', (error) =>
  expect(transientSaveFailure(error)).toBe(true),
)

it('cancels loading on sign-out without discarding the durable note', async () => {
  const outbox = useOutboxStore()
  vi.spyOn(api, 'post').mockImplementation(() => new Promise(() => {}))
  outbox.enqueue(lookup(), payload())
  await settle()
  expect(outbox.request.pending).toBe(true)
  outbox.stop()
  expect(outbox.request.pending).toBe(false)
  const persisted = JSON.parse(localStorage.getItem('booking.outbox.v1.3')!)
  expect(persisted).toHaveLength(1)
  expect(persisted[0].state).toBe('queued')
})

it.each(['NEW_BOOKING_NEEDS_CONFIRM', 'DUPLICATE_RECENT_NOTE'])(
  'stops automatic outbox retries for %s',
  async (code) => {
    const outbox = useOutboxStore(),
      config = { method: 'post', headers: new AxiosHeaders() } as InternalAxiosRequestConfig
    const post = vi
      .spyOn(api, 'post')
      .mockRejectedValue(
        new AxiosError('Review', '', config, undefined, {
          status: code === 'DUPLICATE_RECENT_NOTE' ? 409 : 422,
          statusText: '',
          headers: {},
          config,
          data: { code, message: code },
        }),
      )
    outbox.enqueue(lookup(), payload())
    await settle()
    expect(outbox.entries[0]?.state).toBe('blocked')
    await vi.advanceTimersByTimeAsync(60000)
    expect(post).toHaveBeenCalledTimes(1)
  },
)

it('resumes image upload after a failed upload and reload without resubmitting the saved note', async () => {
  const images = await import('../utils/imageOutbox')
  const file = new File(['evidence'], 'booking.png', { type: 'image/png' })
  vi.spyOn(images, 'loadImages').mockResolvedValue([file])
  const cleanup = vi.spyOn(images, 'removeImages').mockResolvedValue()
  const config = { method: 'post', headers: new AxiosHeaders() } as InternalAxiosRequestConfig
  const post = vi.spyOn(api, 'post')
    .mockResolvedValueOnce({ data: saved() })
    .mockRejectedValueOnce(new AxiosError('offline', 'ERR_NETWORK', config))
    .mockResolvedValueOnce({ data: { id: 88, file_name: 'booking.png', mime_type: 'image/png', size_bytes: 8 } })
  const outbox = useOutboxStore(), entry = outbox.enqueue(lookup(), payload(), 'note', true)!
  await settle()
  expect(entry.savedNote?.note.id).toBe(saved().note.id)
  expect(entry.state).toBe('retrying')
  expect(JSON.parse(localStorage.getItem('booking.outbox.v1.3')!)[0].savedNote.note.id).toBe(saved().note.id)
  outbox.stop()
  outbox.start(3)
  outbox.retry(entry.id)
  await settle()
  expect(outbox.count).toBe(0)
  expect(post.mock.calls.filter(call => call[0].endsWith('/notes'))).toHaveLength(1)
  expect(post.mock.calls.filter(call => call[0].endsWith('/attachments'))).toHaveLength(2)
  expect(cleanup).toHaveBeenCalled()
})

it('can discard failed pending images while keeping the committed note', async () => {
  const images = await import('../utils/imageOutbox')
  vi.spyOn(images, 'loadImages').mockResolvedValue([new File(['evidence'], 'image.png', { type: 'image/png' })])
  const cleanup = vi.spyOn(images, 'removeImages').mockResolvedValue()
  const config = { method: 'post', headers: new AxiosHeaders() } as InternalAxiosRequestConfig
  const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ data: saved() }).mockRejectedValueOnce(new AxiosError('offline', 'ERR_NETWORK', config))
  const outbox = useOutboxStore(), listener = vi.fn(), stop = outbox.subscribe(listener)
  const entry = outbox.enqueue(lookup(), payload(), 'note', true)!
  await settle()
  expect(entry.savedNote).toBeDefined()
  outbox.finishWithoutImages(entry.id)
  expect(outbox.count).toBe(0)
  expect(listener).toHaveBeenCalledWith(entry, expect.objectContaining({ note: expect.objectContaining({ id: saved().note.id }) }))
  expect(post).toHaveBeenCalledTimes(2)
  expect(cleanup).toHaveBeenCalled()
  stop()
})
