import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { defineComponent, h, provide } from 'vue'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { i18n } from '../i18n'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useFoldersStore } from '../stores/folders'
import { lookup, KEY, user, statuses } from '../test/bookingFixtures'
import { CW, FKEY, folder, folderDetail, folderResult, folderLookup } from '../test/folderFixtures'
import { draftStorage } from '../utils/bookingDrafts'
import {
  createShortcutRegistry,
  shortcutRegistryKey,
  useWorkspaceShortcuts,
} from '../composables/useBookingShortcuts'
import BookingWorkspace from './BookingWorkspace.vue'
let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-11-03T08:00:00Z'))
  setActivePinia(createPinia())
  useAuthStore().user = user
  localStorage.clear()
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  useFoldersStore().reset()
  vi.restoreAllMocks()
  vi.useRealTimers()
})
function render() {
  const registry = createShortcutRegistry()
  const Child = defineComponent({
    setup() {
      useWorkspaceShortcuts()
      return () => h(BookingWorkspace)
    },
  })
  wrapper = mount(
    defineComponent({
      setup() {
        provide(shortcutRegistryKey, registry)
        return () => h(Child)
      },
    }),
    {
      attachTo: document.body,
      global: { plugins: [i18n], stubs: { RouterLink: true } },
    },
  )
  return wrapper
}
it('renders breadcrumbs and navigates back by Escape and empty-input Backspace, reusing cached months', async () => {
  const get = vi.spyOn(api, 'get').mockImplementation(async (url) => ({
    data:
      url === '/statuses'
        ? statuses
        : url.startsWith('/folders/')
          ? folderDetail()
          : url === '/bookings/lookup'
            ? folderLookup()
            : {
                kind: 'station',
                query: 'YUL',
                station: { code: 'YUL', name: 'Montreal' },
                sections: [
                  { type: 'hotel', items: [folder()] },
                  { type: 'transportation', items: [] },
                ],
                total: 1,
                page: 1,
                size: 20,
              },
  }))
  render()
  await flushPromises()
  await wrapper!.get('#booking-input').setValue('YUL')
  await vi.advanceTimersByTimeAsync(200)
  await flushPromises()
  await wrapper!.get('.station-section .folder-card').trigger('click')
  await flushPromises()
  expect(wrapper!.get('.folder-breadcrumbs').text()).toContain('Search')
  expect(wrapper!.get('.folder-breadcrumbs').text()).toContain('YUL')
  expect(wrapper!.get('.folder-breadcrumbs').text()).toContain(folder().supplier_name)
  await wrapper!.get('.month-row').trigger('click')
  await flushPromises()
  await wrapper!.get('#booking-note').setValue('Keep this note while browsing')
  await wrapper!.get('#booking-note').trigger('keydown', { key: 'Escape' })
  await flushPromises()
  expect(wrapper!.find('.supplier-folder').exists()).toBe(true)
  expect(draftStorage(user.id).get(FKEY)?.note).toBe('Keep this note while browsing')
  expect((wrapper!.get('#booking-input').element as HTMLInputElement).value).toBe('')
  await wrapper!.get('#booking-input').trigger('keydown', { key: 'Backspace' })
  await flushPromises()
  expect(wrapper!.find('.station-result-title').exists()).toBe(true)
  expect(get.mock.calls.filter((c) => c[0] === '/search')).toHaveLength(1)
})
it('moves keyboard focus to a folder result with the arrow keys', async () => {
  vi.spyOn(api, 'get').mockImplementation(async (url) => ({
    data: url === '/statuses' ? statuses : folderResult(),
  }))
  render()
  await flushPromises()
  await wrapper!.get('#booking-input').setValue(CW)
  await vi.advanceTimersByTimeAsync(200)
  await flushPromises()
  await wrapper!.get('#booking-input').trigger('keydown', { key: 'ArrowDown' })
  expect(document.activeElement).toBe(wrapper!.get('.folder-card').element)
})

it('shows typo suggestions with keyboard navigation and requires a deliberate new-booking confirmation', async () => {
  const missing = {
    ...lookup(0),
    booking_key: 'CW2154655-RDU-2609',
    display_key: 'CW 2154655-RDU-2609',
    resolution: {
      ...lookup().resolution,
      key: 'CW2154655-RDU-2609',
      display_key: 'CW 2154655-RDU-2609',
    },
    group: { ...lookup().group!, cw_number: 'CW2154655' },
    exists: false,
    snapshot: null,
    suggestions: [
      {
        booking_key: KEY,
        display_key: 'CW 2154654-RDU-2609',
        last_status: { code: 'BUNDLE', label: 'Bundle' },
        last_agent: { id: 3, full_name: 'Agent' },
        updated_at: '2026-11-03T08:00:00Z',
        distance: 1,
      },
    ],
  }
  const get = vi.spyOn(api, 'get').mockImplementation(async (url, config) => ({
    data:
      url === '/statuses'
        ? statuses
        : (config?.params as { key?: string } | undefined)?.key === KEY
          ? lookup()
          : missing,
  }))
  render()
  await flushPromises()
  await wrapper!.get('#booking-input').setValue('CW2154655-RDU-2609')
  await vi.advanceTimersByTimeAsync(150)
  await flushPromises()
  await wrapper!.findAll('.status-options button')[2]!.trigger('click')
  expect(wrapper!.get('.save-note').attributes('disabled')).toBeDefined()
  const confirmation = wrapper!
    .findAll('.booking-new-confirm button')
    .find((b) => b.text() === 'This is a new booking')!
  await confirmation.trigger('click')
  expect(wrapper!.get('.save-note').attributes('disabled')).toBeUndefined()
  const noteField = wrapper!.get('#booking-note')
  ;(noteField.element as HTMLTextAreaElement).focus()
  await noteField.trigger('keydown', { key: 'ArrowDown' })
  expect(document.activeElement).toBe(noteField.element)
  await wrapper!.get('#booking-input').trigger('keydown', { key: 'ArrowDown' })
  const suggestion = wrapper!.get('.booking-new-confirm [data-search-result]')
  expect(document.activeElement).toBe(suggestion.element)
  await suggestion.trigger('click')
  await flushPromises()
  const lastLookup = get.mock.calls.filter(call => call[0] === '/bookings/lookup').at(-1)
  expect((lastLookup?.[1]?.params as { key?: string } | undefined)?.key).toBe(KEY)
  expect(wrapper!.find('.booking-new-confirm').exists()).toBe(false)
})
