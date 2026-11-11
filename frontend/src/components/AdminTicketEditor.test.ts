import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'
import { api } from '../api/client'
import { i18n } from '../i18n'
import type { WorkTaskItem } from '../types/api.generated'
import AdminTicketEditor from './AdminTicketEditor.vue'
const ticket: WorkTaskItem = {
  id: 5, booking_key: 'CW2074043-BUD-2610', display_key: 'CW 2074043-BUD-2610',
  supplier_name: 'Example Hotel', creator: { id: 3, full_name: 'Agent' },
  title: 'AF_Non-standard process_Contract issue - CW2074043-BUD-2610', issue_type: 'contract',
  message: 'Please review the attached contract.', edit_token: 'a'.repeat(64), status: 'pending',
  created_at: '2026-11-11T01:00:00Z', handled_by: null, handled_at: null, handling_note: null, attachments: [],
}
const render = () => mount(AdminTicketEditor, { props: { ticket }, global: { plugins: [i18n], stubs: { ElDialog: { template: '<div role="dialog"><slot /></div>' } } } })
afterEach(() => vi.restoreAllMocks())
it('updates the suggested title and sends the original edit lease with the edited content', async () => {
  const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: { ...ticket, status: 'handled' } })
  const wrapper = render()
  await wrapper.findAll('select')[0]!.setValue('cannot_send_rejection_letters')
  expect((wrapper.get('input').element as HTMLInputElement).value).toBe('AF_System Issues_Cannot send rejection letters - CW2074043-BUD-2610')
  await wrapper.get('textarea').setValue('The rejection letter could not be sent on TIM Tool.')
  await wrapper.findAll('select')[1]!.setValue('handled')
  await wrapper.findAll('textarea')[1]!.setValue('Test follow-up completed')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(patch).toHaveBeenCalledWith('/work-tasks/5', expect.objectContaining({
    expected_token: 'a'.repeat(64), status: 'handled', handling_note: 'Test follow-up completed',
    issue_type: 'cannot_send_rejection_letters', message: 'The rejection letter could not be sent on TIM Tool.',
  }), expect.anything())
  expect(wrapper.emitted('saved')).toHaveLength(1)
  wrapper.unmount()
})
it('keeps the draft open on a concurrent edit instead of overwriting a newer ticket', async () => {
  const config = { method: 'patch', headers: new AxiosHeaders() } as InternalAxiosRequestConfig
  vi.spyOn(api, 'patch').mockRejectedValue(new AxiosError('Conflict', '', config, undefined, {
    status: 409, statusText: '', config, headers: {}, data: { code: 'VERSION_CONFLICT', message: 'Changed' },
  }))
  const wrapper = render()
  await wrapper.get('textarea').setValue('Keep my unsaved correction for review.')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.emitted('saved')).toBeUndefined()
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('Keep my unsaved correction for review.')
  expect(wrapper.find('[role=alert]').exists()).toBe(true)
  wrapper.unmount()
})
it('rejects Vietnamese content before sending an admin edit', async () => {
  const patch = vi.spyOn(api, 'patch')
  const wrapper = render()
  await wrapper.get('textarea').setValue('Không thể gửi thư từ chối')
  await wrapper.get('form').trigger('submit')
  expect(patch).not.toHaveBeenCalled()
  wrapper.unmount()
})
