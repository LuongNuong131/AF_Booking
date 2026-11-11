import { createPinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { i18n } from '../i18n'
import NoteSearchView from './NoteSearchView.vue'
import PageControls from '../components/PageControls.vue'
const hit = { booking_key: 'CW2074043-BUD-2610', display_key: 'CW 2074043 - BUD - 2610', note_id: 7, note: 'Contract <img src=x> confirmed', agent: { id: 2, full_name: 'Agent One' }, status: { id: 1, code: 'New', label: 'New' }, position: 'Parking', created_at: '2026-11-11T02:00:00Z', match_count: 2, supplier_name: 'Hotel One', station_code: 'BUD', supplier_type: 'hotel' }
const response = (page = 1) => ({ items: [hit], total: 21, page, size: 20, date_from: '2026-10-13', date_to: '2026-11-11', timezone: 'Asia/Ho_Chi_Minh', strategy: 'like' })
const mounted: VueWrapper[] = []
afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  vi.restoreAllMocks()
})
async function setup(url = '/search/notes?q=contract&agent_id=2') {
  const get = vi.spyOn(api, 'get').mockImplementation(async (path, config) => ({ data: path === '/search/notes' ? response((config?.params as { page: number }).page) : path === '/reports/center/options' ? { today: '2026-11-11', timezone: 'Asia/Ho_Chi_Minh' } : [] }))
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/search/notes', name: 'note-search', component: NoteSearchView }, { path: '/summary', name: 'summary', component: { template: '<div />' } }, { path: '/booking/:key', name: 'booking', component: { template: '<div />' } }] })
  await router.push(url); await router.isReady()
  const wrapper = mount(NoteSearchView, { global: { plugins: [createPinia(), i18n, router] } })
  mounted.push(wrapper)
  await flushPromises()
  return { wrapper, router, get, searches: () => get.mock.calls.filter(call => call[0] === '/search/notes') }
}
it('keeps unsubmitted edits separate from applied results and paging, and restores URL filters', async () => {
  const { wrapper, router, searches } = await setup()
  expect(wrapper.get('.note-search-hit mark').text()).toBe('Contract')
  expect(wrapper.findAll('img')).toHaveLength(0)
  expect(wrapper.get('.note-search-hit').text()).toContain('<img src=x>')
  await wrapper.get('#notes-keyword').setValue('rejection')
  expect(wrapper.get('.note-search-draft-hint').text()).toContain('Search')
  wrapper.getComponent(PageControls).vm.$emit('change', 2)
  await flushPromises()
  expect(searches().at(-1)?.[1]?.params).toMatchObject({ q: 'contract', agent_id: '2', page: 2 })
  expect((wrapper.get('#notes-keyword').element as HTMLInputElement).value).toBe('rejection')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(router.currentRoute.value.query).toEqual({ q: 'rejection', agent_id: '2' })
  await router.push('/search/notes?q=contract&agent_id=2')
  await flushPromises()
  expect((wrapper.get('#notes-keyword').element as HTMLInputElement).value).toBe('contract')
  expect(wrapper.find('.note-search-draft-hint').exists()).toBe(false)
  wrapper.unmount()
})
it('does not request invalid URL filters and validates the inclusive date range', async () => {
  const { wrapper, searches } = await setup('/search/notes?q=contract&date_from=2026-11-12&date_to=2026-11-11')
  expect(searches()).toHaveLength(0)
  expect(wrapper.get('.field-error').text()).toContain('start date')
  await wrapper.get('#notes-date-from').setValue('2026-05-01')
  expect(wrapper.get('.field-error').text()).toContain('180')
  await wrapper.get('#notes-date-from').setValue('2026-11-01')
  await wrapper.get('form').trigger('submit'); await flushPromises()
  expect(searches()).toHaveLength(1)
  wrapper.unmount()
})
it('corrects an outdated page link and clears results with the filters', async () => {
  const { wrapper, router, searches } = await setup('/search/notes?q=contract&page=99')
  expect(router.currentRoute.value.query.page).toBe('2')
  expect(searches()).toHaveLength(2)
  await wrapper.get('.note-search-results-heading button').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.query).toEqual({})
  expect(wrapper.find('.note-search-hit').exists()).toBe(false)
  expect(wrapper.find('.note-search-welcome').exists()).toBe(true)
  wrapper.unmount()
})
