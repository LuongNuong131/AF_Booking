import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'
import { api } from '../api/client'
import { useTasksStore } from './tasks'
import { useAuthStore } from './auth'
import { parseServerFrame } from '../api/realtime-protocol'
import { user, KEY, event, task } from '../test/bookingFixtures'
import type { TaskDueData } from '../types/api.generated'

function due(t = task()): TaskDueData {
  return { task: t, notification_id: 10, created_at: '2026-11-03T08:00:00.000Z' }
}
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-11-03T08:00:00Z'))
  setActivePinia(createPinia())
  useAuthStore().user = user
  vi.spyOn(api, 'get').mockImplementation(async (url) => ({
    data: url === '/notifications' ? { items: [], unread_count: 0 } : { items: [], total: 0 },
  }))
})
afterEach(() => {
  useTasksStore().reset()
  vi.restoreAllMocks()
  vi.useRealTimers()
})
it('validates task.due frames, keeps a persistent reminder and deduplicates them', () => {
  const store = useTasksStore()
  expect(parseServerFrame({ event: 'task.due', data: due() })).not.toBeNull()
  expect(parseServerFrame({ event: 'task.due', data: { task: { id: 1 } } })).toBeNull()
  expect(store.incoming(due())).toBe(true)
  expect(store.incoming(due())).toBe(false)
  expect(store.dueCount).toBe(1)
  expect(store.reminderTasks).toHaveLength(1)
})
it('loads a due summary and ignores a response invalidated by a newer event', async () => {
  let finish!: (r: unknown) => void
  vi.spyOn(api, 'get').mockImplementation(
    () =>
      new Promise((done) => {
        finish = done
      }),
  )
  const store = useTasksStore(),
    reading = store.refreshDue(true)
  await Promise.resolve()
  store.incoming(due())
  finish({ data: { items: [], total: 0 } })
  await reading
  expect(store.dueCount).toBe(1)
  expect(store.summaryOpen).toBe(true)
})
it('optimistically completes, then restores on error while preserving a booking update', async () => {
  let fail!: (r: unknown) => void
  vi.spyOn(api, 'post').mockImplementation(
    () =>
      new Promise((_done, reject) => {
        fail = reject
      }),
  )
  vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [task()], total: 1 } })
  const store = useTasksStore()
  store.setDueTasks([task()])
  store.incoming(due())
  const changing = store.mutate(store.records[1]!, 'complete')
  await Promise.resolve()
  expect(store.dueCount).toBe(0)
  expect(store.records[1]?.status).toBe('done')
  store.bookingUpdated(event(2, 5))
  const config = { method: 'post', headers: new AxiosHeaders() } as InternalAxiosRequestConfig
  fail(new AxiosError('offline', 'ERR_NETWORK', config))
  expect(await changing).toBe(false)
  expect(store.records[1]?.status).toBe('pending')
  expect(store.records[1]?.booking.last_agent?.id).toBe(5)
  expect(store.records[1]?.booking_changed_since).toBe(true)
  expect(store.reminderTasks).toHaveLength(1)
})
it('blocks double actions and never resurrects a completed task from a delayed due frame', async () => {
  let finish!: (r: unknown) => void
  const post = vi.spyOn(api, 'post').mockImplementation(
    () =>
      new Promise((done) => {
        finish = done
      }),
  )
  const store = useTasksStore()
  store.setDueTasks([task()])
  const changing = store.mutate(store.records[1]!, 'complete')
  await Promise.resolve()
  expect(await store.mutate(task(), 'complete')).toBe(false)
  await store.refreshDue(true)
  await store.refreshList()
  expect(api.get).not.toHaveBeenCalled()
  expect(store.records[1]?.status).toBe('done')
  finish({
    data: {
      ...task(),
      status: 'done',
      completed_at: '2026-11-03T08:00:00Z',
      is_due: false,
      is_overdue: false,
    },
  })
  expect(await changing).toBe(true)
  expect(store.incoming(due())).toBe(false)
  expect(post).toHaveBeenCalledTimes(1)
  expect(store.noteSuggestion).toBe(KEY)
})
it('reuses a create UUID on manual retry and sends local date/time only', async () => {
  const config = { method: 'post', headers: new AxiosHeaders() } as InternalAxiosRequestConfig
  const post = vi
    .spyOn(api, 'post')
    .mockRejectedValueOnce(new AxiosError('timeout', 'ECONNABORTED', config))
    .mockResolvedValueOnce({ data: task() })
  const store = useTasksStore(),
    ctx = { signal: new AbortController().signal, timeoutMs: 10000 },
    body = { remind_date: '2026-11-04', remind_time: '09:00', message: 'Check mail' }
  await store.create(ctx, KEY, body).catch(() => {})
  await store.create(ctx, KEY, body)
  expect(post.mock.calls[0]?.[1]).toEqual(post.mock.calls[1]?.[1])
  expect(post.mock.calls[1]?.[1]).not.toHaveProperty('remind_at')
})
it('updates booking warnings in place without reloading the task list', () => {
  const store = useTasksStore()
  store.setDueTasks([task()])
  store.bookingUpdated({ ...event(2, 5), is_done: true })
  expect(store.records[1]?.booking.is_done).toBe(true)
  expect(store.records[1]?.booking_changed_since).toBe(true)
  expect(api.get).not.toHaveBeenCalled()
})
it('retries an active page read interrupted by a due event without polling', async () => {
  let finish!: (result: unknown) => void
  let pageReads = 0
  vi.spyOn(api, 'get').mockImplementation((url) => {
    if (url === '/tasks' && pageReads++ === 0)
      return new Promise((done) => {
        finish = done
      })
    return Promise.resolve({ data: { items: [task()], total: 1, page: 1, size: 10 } })
  })
  const store = useTasksStore()
  store.setListActive(true)
  const reading = store.refreshList()
  await Promise.resolve()
  store.incoming(due())
  finish({ data: { items: [], total: 0, page: 1, size: 10 } })
  await reading
  await vi.advanceTimersByTimeAsync(250)
  expect(pageReads).toBe(2)
  expect(store.items).toHaveLength(1)
  await vi.advanceTimersByTimeAsync(60000)
  expect(pageReads).toBe(2)
})
it('keeps reminders until dismissal and clears private state on reset', () => {
  const store = useTasksStore()
  store.incoming(due())
  store.openDialog(KEY)
  store.dismissReminder(1)
  expect(store.dueCount).toBe(1)
  expect(store.reminderTasks).toHaveLength(0)
  store.reset()
  expect(store.dueCount).toBe(0)
  expect(store.dialog).toBeNull()
  expect(store.records).toEqual({})
})
