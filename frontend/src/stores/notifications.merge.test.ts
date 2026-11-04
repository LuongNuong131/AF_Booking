import { it, expect, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api/client'
import { useNotificationsStore } from './notifications'
import { KEY } from '../test/bookingFixtures'
it('refreshes a merged unread watch notification with its existing ID without incrementing the badge', async () => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  const data = {
    id: 1,
    booking_key: KEY,
    display_key: KEY.replace('CW', 'CW '),
    type: 'watch_update' as const,
    by_agent_name: 'Agent',
    created_at: '2026-11-03T08:00:00.000Z',
    merged_count: 1,
  }
  const get = vi
    .spyOn(api, 'get')
    .mockResolvedValue({
      data: {
        items: [
          {
            ...data,
            read_at: null,
            by_agent: { id: 3, full_name: 'Agent' },
            note_id: 2,
            task_id: null,
          },
        ],
        unread_count: 1,
      },
    })
  const store = useNotificationsStore()
  await store.refresh()
  store.incoming({ ...data, merged_count: 3 })
  expect(store.unread).toBe(1)
  await vi.advanceTimersByTimeAsync(1000)
  expect(get).toHaveBeenCalledTimes(2)
  store.reset()
  vi.restoreAllMocks()
  vi.useRealTimers()
})
