import { afterEach, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { user } from '../test/bookingFixtures'
import { folder, CW } from '../test/folderFixtures'
import FolderCard from './FolderCard.vue'
afterEach(() => vi.restoreAllMocks())
it('shows supplier identity, type, station, months, latest status and stale/open badges', async () => {
  setActivePinia(createPinia())
  useAuthStore().user = user
  const wrapper = mount(FolderCard, {
    props: { folder: folder() },
    global: { plugins: [i18n] },
  })
  for (const text of [
    CW,
    folder().supplier_name,
    'Hotel',
    'YUL',
    '3 month(s)',
    '2 open',
    '1 stale month(s)',
    'Bundle',
    'CW 2154927-YUL-2609',
  ])
    expect(wrapper.text()).toContain(text)
  expect(wrapper.find('svg').exists()).toBe(true)
  expect(wrapper.get('time').attributes('datetime')).toBe(folder().last_activity_at)
  await wrapper.get('button').trigger('click')
  expect(wrapper.emitted('open')?.[0]).toEqual([CW])
  wrapper.unmount()
})
