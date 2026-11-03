import { onScopeDispose, ref, shallowRef } from 'vue'
import { useRequest } from './useRequest'
import { useBookingsStore } from '../stores/bookings'
import { timeouts } from '../config/timeouts'
import type { RequestFailure } from '../api/errors'
import type { BookingItem, BookingUpdatedData } from '../types/api.generated'
import { patchBooking } from '../utils/patchBooking'
export { patchBooking }
// Only hydrate changed rows: the event intentionally does not contain the note preview.
export function useBookingRows(
  accept: (event: BookingUpdatedData) => boolean,
  hydrate: (item: BookingItem, event: BookingUpdatedData) => void,
) {
  const store = useBookingsStore()
  const request = useRequest((ctx, key: string) => store.lookup(ctx, key, true), {
    timeoutMs: timeouts.lookup,
    retry: true,
  })
  const queue = new Map<string, BookingUpdatedData>(),
    failures = new Map<string, BookingUpdatedData>()
  const error = shallowRef<RequestFailure | null>(null),
    failedCount = ref(0)
  let running = false,
    stopped = false,
    sequence = 0
  const latestVersions = new Map<string, number>()
  const events: { sequence: number; event: BookingUpdatedData }[] = []
  async function drain() {
    if (running || stopped) return
    running = true
    try {
      while (queue.size && !stopped) {
        const [key, event] = queue.entries().next().value!
        queue.delete(key)
        const result = await request.run(key)
        if (
          result?.snapshot &&
          !stopped &&
          result.snapshot.version >= Math.max(event.version, latestVersions.get(key) ?? 0)
        ) {
          hydrate(result.snapshot, event)
          failures.delete(key)
        } else if (!stopped && request.error.value) {
          failures.set(key, event)
          error.value = request.error.value
        }
        failedCount.value = failures.size
        if (!failures.size) error.value = null
      }
    } finally {
      running = false
    }
  }
  function enqueue(event: BookingUpdatedData) {
    if (!accept(event)) return
    queue.delete(event.booking_key)
    queue.set(event.booking_key, event)
    while (queue.size > 40) queue.delete(queue.keys().next().value!)
    void drain()
  }
  const unsubscribe = store.subscribe((event) => {
    latestVersions.delete(event.booking_key)
    latestVersions.set(event.booking_key, event.version)
    while (latestVersions.size > 2000) latestVersions.delete(latestVersions.keys().next().value!)
    failures.delete(event.booking_key)
    failedCount.value = failures.size
    if (!failures.size) error.value = null
    events.push({ sequence: ++sequence, event })
    if (events.length > 2000) events.shift()
    enqueue(event)
  })
  function retry() {
    for (const event of failures.values()) queue.set(event.booking_key, event)
    void drain()
  }
  onScopeDispose(() => {
    stopped = true
    request.cancel()
    queue.clear()
    unsubscribe()
  })
  function replay(since: number) {
    for (const item of events) if (item.sequence > since) enqueue(item.event)
  }
  return {
    request,
    retry,
    error,
    failedCount,
    version: () => sequence,
    replay,
  }
}
