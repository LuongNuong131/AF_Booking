import { it, expect, vi, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api/client'
import { useOutboxStore } from './outbox'
import { useAuthStore } from './auth'
import { useBookingsStore } from './bookings'
import { KEY, user, statuses, lookup, item } from '../test/bookingFixtures'
afterEach(() => {
  useOutboxStore().stop()
  vi.restoreAllMocks()
  localStorage.clear()
})
it('persists an invoice-only operation, reopens it and retries PUT without notes or takeover', async () => {
  setActivePinia(createPinia())
  localStorage.clear()
  const auth = useAuthStore()
  auth.user = user
  auth.token = 'test-only'
  auth.ready = true
  useBookingsStore().statuses = structuredClone(statuses)
  let online = false
  vi.spyOn(navigator, 'onLine', 'get').mockImplementation(() => online)
  const outbox = useOutboxStore()
  outbox.start(user.id)
  const base = lookup()
  base.invoices = []
  const before = structuredClone(base.snapshot!)
  const entry = outbox.enqueueInvoices(base, {
    add: ['INV100'],
    no_invoice: false,
  })!
  expect(entry.operation).toBe('invoice')
  expect(entry.preview.last_agent).toEqual(before.last_agent)
  expect(entry.preview.updated_at).toBe(before.updated_at)
  expect(entry.preview.invoice_count).toBe(1)
  outbox.stop()
  outbox.start(user.id)
  expect(outbox.entries).toHaveLength(1)
  expect(outbox.entries[0]!.id).toBe(entry.id)
  const post = vi.spyOn(api, 'post'),
    put = vi.spyOn(api, 'put').mockResolvedValue({
      data: {
        snapshot: {
          ...item(2),
          invoice_state: 'has_invoice',
          invoice_count: 1,
          invoices_preview: ['INV100'],
        },
        invoices: [],
        skipped_duplicates: [],
        warnings: [],
      },
    })
  online = true
  await outbox.flush()
  expect(put).toHaveBeenCalledWith(
    `/bookings/${KEY}/invoices`,
    { add: ['INV100'], no_invoice: false },
    expect.any(Object),
  )
  expect(post).not.toHaveBeenCalled()
  expect(outbox.count).toBe(0)
})
