import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { i18n } from '../i18n'
import BookingTicketPanel from './BookingTicketPanel.vue'
import StagedImages from './StagedImages.vue'
const key = 'CW2074043-BUD-2610'
afterEach(() => vi.restoreAllMocks())
it('generates both exact subjects and requires English content', async () => {
  vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [] } })
  const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 4 } })
  const wrapper = mount(BookingTicketPanel, { props: { bookingKey: key }, global: { plugins: [i18n], stubs: { RouterLink: true } } })
  expect((wrapper.get('input[readonly]').element as HTMLInputElement).value).toBe(`AF_Non-standard process_Contract issue - ${key}`)
  await wrapper.get('select').setValue('cannot_send_rejection_letters')
  expect((wrapper.get('input[readonly]').element as HTMLInputElement).value).toBe(`AF_System Issues_Cannot send rejection letters - ${key}`)
  await wrapper.get('textarea').setValue('Không thể gửi thư từ chối')
  await wrapper.get('form').trigger('submit')
  expect(post).not.toHaveBeenCalled()
  await wrapper.get('textarea').setValue('Cannot send the rejection letter on TIM Tool.')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(post).toHaveBeenCalledWith(`/bookings/${key}/work-tasks`, expect.objectContaining({ issue_type: 'cannot_send_rejection_letters', message: 'Cannot send the rejection letter on TIM Tool.' }), expect.anything())
  wrapper.unmount()
})
it('keeps the created ticket when an image fails and retries only remaining images', async () => {
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [] } })
  const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ data: { id: 7 } }).mockResolvedValueOnce({ data: {} }).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: {} })
  const wrapper = mount(BookingTicketPanel, { props: { bookingKey: key }, global: { plugins: [i18n], stubs: { RouterLink: true } } })
  const files = [new File(['one'], 'one.png', { type: 'image/png' }), new File(['two'], 'two.png', { type: 'image/png' })]
  wrapper.getComponent(StagedImages).vm.$emit('update:modelValue', files)
  await wrapper.get('textarea').setValue('Please review the contract and attached images.')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()
  expect(wrapper.getComponent(StagedImages).props('modelValue')).toHaveLength(1)
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(post.mock.calls.filter(call => call[0].endsWith('/work-tasks'))).toHaveLength(1)
  expect(post.mock.calls.filter(call => call[0] === '/work-tasks/7/attachments')).toHaveLength(3)
  expect(wrapper.getComponent(StagedImages).props('modelValue')).toEqual([])
  wrapper.unmount()
})
