import { ref, shallowReactive } from 'vue'
import { defineStore } from 'pinia'
import type {
  BookingUpdatedData,
  LockHolder,
  LockInfo,
  WebSocketClientFrame,
  WebSocketServerFrame,
} from '../types/api.generated'
import { parseBookingKey } from '../utils/bookingKey'

export type ConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'superseded'
export const useRealtimeStore = defineStore('realtime', () => {
  const state = ref<ConnectionState>('disconnected')
  const locks = ref<Record<string, LockHolder & { expires_at?: string }>>({})
  const bookingUpdates = shallowReactive(new Map<string, BookingUpdatedData>())
  const activeBookingKey = ref<string | null>(null)
  const revision = ref(0)
  let sender: ((frame: WebSocketClientFrame) => boolean) | null = null
  function bindSender(value: typeof sender): void {
    sender = value
  }
  function apply(frame: WebSocketServerFrame): void {
    switch (frame.event) {
      case 'lock.snapshot':
        locks.value = Object.fromEntries(frame.data.locks.map((l: LockInfo) => [l.booking_key, l]))
        break
      case 'lock.acquired':
        locks.value[frame.data.booking_key] = frame.data
        break
      case 'lock.released':
        if (locks.value[frame.data.booking_key]?.user_id === frame.data.user_id)
          delete locks.value[frame.data.booking_key]
        break
      case 'lock.denied':
        locks.value[frame.data.booking_key] = frame.data
        break
      case 'booking.updated': {
        const old = bookingUpdates.get(frame.data.booking_key)
        if (!old || frame.data.version > old.version) {
          bookingUpdates.delete(frame.data.booking_key)
          bookingUpdates.set(frame.data.booking_key, frame.data)
          while (bookingUpdates.size > 2000)
            bookingUpdates.delete(bookingUpdates.keys().next().value!)
          revision.value++
        }
      }
    }
  }
  function acquire(key: string): boolean {
    const parsed = parseBookingKey(key)
    if (!parsed || !('key' in parsed) || parsed.key !== key) return false
    activeBookingKey.value = key
    return sender?.({ event: 'lock.acquire', data: { booking_key: key } }) ?? false
  }
  function release(): void {
    if (activeBookingKey.value)
      sender?.({
        event: 'lock.release',
        data: { booking_key: activeBookingKey.value },
      })
    activeBookingKey.value = null
  }
  function reset(): void {
    locks.value = {}
    bookingUpdates.clear()
    activeBookingKey.value = null
    state.value = 'disconnected'
  }
  return {
    state,
    locks,
    bookingUpdates,
    activeBookingKey,
    revision,
    bindSender,
    apply,
    acquire,
    release,
    reset,
  }
})
