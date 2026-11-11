import { expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { parseServerFrame } from './realtime-protocol'
import { event, item, task } from '../test/bookingFixtures'
import { patchBooking } from '../composables/useBookingRows'
import { useTasksStore } from '../stores/tasks'
it('accepts a rebuilt booking with no surviving note and clears client summaries', () => {
  setActivePinia(createPinia())
  const changed = {
    ...event(),
    last_agent_id: null,
    last_agent_name: null,
    status_code: null,
    position: null,
    snapshot_rebuilt: true,
  }
  expect(parseServerFrame({ event: 'booking.updated', data: changed })).not.toBeNull()
  const row = patchBooking(item(), changed, [])
  expect(row.last_status).toBeNull()
  expect(row.last_agent).toBeNull()
  const tasks = useTasksStore()
  tasks.setDueTasks([task()])
  tasks.bookingUpdated(changed)
  expect(tasks.records[1]?.booking.last_status).toBeNull()
  expect(tasks.records[1]?.booking_changed_since).toBe(true)
  tasks.reset()
})
it('validates catalogue invalidations without granting arbitrary event types', () => {
  expect(
    parseServerFrame({
      event: 'catalog.updated',
      data: { resource: 'suppliers', snapshots_changed: true },
    }),
  ).not.toBeNull()
  expect(
    parseServerFrame({
      event: 'catalog.updated',
      data: { resource: 'statuses', snapshots_changed: true },
    }),
  ).not.toBeNull()
  expect(
    parseServerFrame({
      event: 'catalog.updated',
      data: { resource: 'passwords', snapshots_changed: true },
    }),
  ).toBeNull()
})
