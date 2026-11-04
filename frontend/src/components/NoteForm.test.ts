import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { i18n } from '../i18n'
import { statuses } from '../test/bookingFixtures'
import NoteForm from './NoteForm.vue'
function render() {
  return mount(NoteForm, {
    props: {
      statusCode: 'REJECTION',
      note: '',
      statuses,
      pending: false,
      canSave: true,
      online: true,
      state: 'idle',
      hasDraft: false,
    },
    global: { plugins: [i18n] },
  })
}
it('blocks required empty note even if the parent mistakenly passes canSave', async () => {
  const wrapper = render()
  expect(wrapper.get('.save-note').attributes('disabled')).toBeDefined()
  await wrapper.get('form').trigger('submit')
  expect(wrapper.emitted('save')).toBeUndefined()
  await wrapper.setProps({ note: 'Supplier reply received' })
  expect(wrapper.get('.save-note').attributes('disabled')).toBeUndefined()
  await wrapper.get('form').trigger('submit')
  expect(wrapper.emitted('save')).toHaveLength(1)
  wrapper.unmount()
})
it('coalesces same-tick double submits and respects pending and permission state', async () => {
  const wrapper = render()
  await wrapper.setProps({ note: 'One intended operation' })
  const form = wrapper.get('form').element
  form.dispatchEvent(new Event('submit', { cancelable: true }))
  form.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(wrapper.emitted('save')).toHaveLength(1)
  await nextTick()
  await wrapper.setProps({ pending: true })
  await wrapper.get('form').trigger('submit')
  expect(wrapper.emitted('save')).toHaveLength(1)
  await wrapper.setProps({ pending: false, canSave: false })
  await wrapper.get('form').trigger('submit')
  expect(wrapper.emitted('save')).toHaveLength(1)
  wrapper.unmount()
})
