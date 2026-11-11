import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { i18n } from '../i18n'
import { useNotificationsStore } from '../stores/notifications'
import BookingTicketHistory from './BookingTicketHistory.vue'
import PageControls from './PageControls.vue'
const bookingKey = 'CW2074043-BUD-2610'
const ticket = (status: string, id = 1) => ({ id, title: `Contract issue ${id}`, message: 'Please check this contract.', status, creator: { id: 2, full_name: 'Agent One' }, created_at: '2026-11-11T02:00:00Z', handled_by: status === 'handled' ? { id: 3, full_name: 'QC One' } : null, handled_at: '2026-11-11T03:00:00Z', handling_note: 'Verified contract.' })
afterEach(() => vi.restoreAllMocks())
const mountHistory = () => mount(BookingTicketHistory, { props: { bookingKey }, global: { plugins: [createPinia(), i18n], stubs: { RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } } } })
it('shows both counts, handler details and a link that opens the handled ticket', async () => {
  const get = vi.spyOn(api, 'get').mockImplementation(async (_url, config) => {
    const { status } = config?.params as { status: string }
    return { data: { items: [ticket(status)], total: status === 'pending' ? 8 : 1 } }
  })
  const wrapper = mountHistory()
  await flushPromises()
  expect(get.mock.calls.map(call => call[1]?.params)).toEqual([
    { booking_key: bookingKey, status: 'pending', page: 1, size: 5 },
    { booking_key: bookingKey, status: 'handled', page: 1, size: 5 },
  ])
  expect(wrapper.get('.booking-ticket-tabs').text()).toContain('8')
  wrapper.getComponent(PageControls).vm.$emit('change', 2)
  await flushPromises()
  expect(get.mock.lastCall?.[1]?.params).toMatchObject({ status: 'pending', page: 2 })
  await wrapper.get('.booking-ticket-tabs button:last-child').trigger('click')
  expect(wrapper.get('.booking-ticket-record-outcome').text()).toContain('QC One')
  expect(wrapper.get('.booking-ticket-record-outcome').text()).toContain('Verified contract.')
  expect(JSON.parse(wrapper.get('.booking-ticket-history-title').attributes('data-to') ?? '{}').query).toEqual({ booking_key: bookingKey, status: 'handled', ticket_id: 1 })
  useNotificationsStore().unread++
  await flushPromises()
  expect(get).toHaveBeenCalledTimes(5)
  wrapper.unmount()
})
it('opens handled history initially when no ticket is waiting and emits the create action', async () => {
  vi.spyOn(api, 'get').mockImplementation(async (_url, config) => {
    const { status } = config?.params as { status: string }
    return { data: { items: status === 'pending' ? [] : [ticket('handled')], total: status === 'pending' ? 0 : 1 } }
  })
  const wrapper = mountHistory()
  await flushPromises()
  expect(wrapper.get('.booking-ticket-tabs button:last-child').attributes('aria-pressed')).toBe('true')
  await wrapper.get('.booking-ticket-history-footer button').trigger('click')
  expect(wrapper.emitted('create')).toHaveLength(1)
  await wrapper.vm.showCreated()
  await flushPromises()
  expect(wrapper.get('.booking-ticket-tabs button:first-child').attributes('aria-pressed')).toBe('true')
  wrapper.unmount()
})
it('still chooses the handled list when a notification interrupts the first load', async () => {
  type Reply = { data: { items: ReturnType<typeof ticket>[]; total: number } }
  const replies: Array<(value: Reply) => void> = []
  vi.spyOn(api, 'get').mockImplementation(() => new Promise<Reply>(resolve => replies.push(resolve)))
  const wrapper = mountHistory()
  await flushPromises()
  useNotificationsStore().unread++
  await flushPromises()
  expect(replies).toHaveLength(4)
  replies[2]!({ data: { items: [], total: 0 } })
  replies[3]!({ data: { items: [ticket('handled')], total: 1 } })
  await flushPromises()
  expect(wrapper.get('.booking-ticket-tabs button:last-child').attributes('aria-pressed')).toBe('true')
  wrapper.unmount()
})
