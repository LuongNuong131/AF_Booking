import { ref } from 'vue'
import { defineStore } from 'pinia'
import { parseBookingKey } from '../utils/bookingKey'
import { readStorage, writeStorage } from '../utils/storage'
export const useRecentBookingsStore = defineStore('recent-bookings', () => {
  const items = ref<string[]>([])
  let owner: number | null = null
  function reset(id: number | null = null) {
    owner = id
    items.value = []
    if (id === null) return
    try {
      const value = JSON.parse(readStorage('localStorage', `booking.recent.${id}`) ?? '[]')
      if (Array.isArray(value))
        items.value = [
          ...new Set(
            value.filter(
              (v): v is string =>
                typeof v === 'string' &&
                (() => {
                  const p = parseBookingKey(v)
                  return !!p && 'key' in p && p.key === v
                })(),
            ),
          ),
        ].slice(0, 10)
    } catch {
      /* corrupted history is discarded */
    }
  }
  function remember(key: string) {
    const parsed = parseBookingKey(key)
    if (owner === null || !parsed || !('key' in parsed) || parsed.key !== key) return
    items.value = [key, ...items.value.filter((k) => k !== key)].slice(0, 10)
    writeStorage('localStorage', `booking.recent.${owner}`, JSON.stringify(items.value))
  }
  return { items, reset, remember }
})
