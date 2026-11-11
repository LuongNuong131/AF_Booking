import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { i18n } from '../i18n'
import TicketCopy from './TicketCopy.vue'
afterEach(() => vi.unstubAllGlobals())
it('copies the exact subject and multiline English body', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  const wrapper = mount(TicketCopy, { props: { title: 'AF_System Issues_Cannot send rejection letters', message: 'Please check these invoice.\n\nCW2114762-DUB-2610\nCW2129797-LYS-2610' }, global: { plugins: [i18n] } })
  await wrapper.findAll('button')[2]!.trigger('click')
  await flushPromises()
  expect(writeText).toHaveBeenCalledWith('AF_System Issues_Cannot send rejection letters\n\nPlease check these invoice.\n\nCW2114762-DUB-2610\nCW2129797-LYS-2610')
  expect(wrapper.find('[role=status]').exists()).toBe(true)
  wrapper.unmount()
})
it('provides the exact text for manual copying when the browser denies clipboard access', async () => {
  vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new DOMException('Denied', 'NotAllowedError')) } })
  const wrapper = mount(TicketCopy, { props: { title: 'Contract issue', message: 'Please check the attached contract.\nBooking CW2074043-BUD-2610' }, global: { plugins: [i18n] } })
  await wrapper.findAll('button')[1]!.trigger('click')
  await flushPromises()
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('Please check the attached contract.\nBooking CW2074043-BUD-2610')
  expect(wrapper.get('textarea').attributes('readonly')).toBeDefined()
  expect(wrapper.find('[role=status]').exists()).toBe(false)
  wrapper.unmount()
})
