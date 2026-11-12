import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api/client'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { useCollaborationStore } from '../stores/collaboration'
import { user, KEY } from '../test/bookingFixtures'
import FolderFollowButton from './FolderFollowButton.vue'
beforeEach(() => { setActivePinia(createPinia()); useAuthStore().user = user })
afterEach(() => vi.restoreAllMocks())
it('loads a persisted follow when no initial flag is supplied, as after a page reload', async () => {
  const send = vi.spyOn(api, 'request').mockResolvedValue({ data: { following: true } })
  const wrapper = mount(FolderFollowButton, { props: { folderKey: 'CW2154654-RDU' }, global: { plugins: [i18n] } })
  await flushPromises()
  expect(send).toHaveBeenCalledWith(expect.objectContaining({ method: 'GET' }))
  expect(wrapper.get('button').text()).toBe('Unfollow folder')
  expect(wrapper.get('button').attributes('aria-pressed')).toBe('true')
  wrapper.unmount()
})
it('unfollows a known folder only after acknowledgement and retains the booking follow', async () => {
  const send = vi.spyOn(api, 'request').mockResolvedValue({ data: { following: false } })
  const store = useCollaborationStore()
  store.seed(KEY, true)
  const wrapper = mount(FolderFollowButton, { props: { folderKey: 'CW2154654-RDU', following: true }, global: { plugins: [i18n] } })
  expect(send).not.toHaveBeenCalled()
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(send).toHaveBeenCalledWith(expect.objectContaining({ method: 'DELETE' }))
  expect(wrapper.get('button').text()).toBe('Follow folder')
  expect(store.watched[KEY]).toBe(true)
  wrapper.unmount()
})
