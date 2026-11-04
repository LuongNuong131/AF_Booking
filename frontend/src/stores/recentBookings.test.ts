import { it, expect } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useRecentBookingsStore } from './recentBookings'
it('keeps ten canonical keys per account, deduplicates and restores without sharing another account history', () => {
  setActivePinia(createPinia())
  localStorage.clear()
  const store = useRecentBookingsStore()
  store.reset(3)
  for (let i = 1; i <= 12; i++) store.remember(`CW1234567-RDU-26${String(i).padStart(2, '0')}`)
  expect(store.items).toHaveLength(10)
  const key = store.items[3]!
  store.remember(key)
  expect(store.items[0]).toBe(key)
  expect(store.items).toHaveLength(10)
  store.reset(5)
  expect(store.items).toEqual([])
  store.reset(3)
  expect(store.items[0]).toBe(key)
  localStorage.setItem('booking.recent.5', JSON.stringify(['invalid', 'CW 1234567-RDU-2601']))
  store.reset(5)
  expect(store.items).toEqual([])
})
