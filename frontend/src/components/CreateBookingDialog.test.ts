import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'
import { api } from '../api/client'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { item, KEY, lookup, user } from '../test/bookingFixtures'
import type { BookingLookup } from '../types/api.generated'
import CreateBookingDialog from './CreateBookingDialog.vue'

let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  useAuthStore().user = user
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  useUiStore().clearNotices()
  vi.restoreAllMocks()
  vi.useRealTimers()
})
function render() {
  wrapper = mount(CreateBookingDialog, {
    global: {
      plugins: [i18n],
      stubs: {
        ElDialog: defineComponent({ template: '<section><slot name="header" /><slot /></section>' }),
      },
    },
  })
  return wrapper
}
function missing(groupExists = false): BookingLookup {
  return {
    ...lookup(),
    exists: false,
    version: 0,
    snapshot: null,
    group_exists: groupExists,
    group: groupExists ? lookup().group : null,
    history: { items: [], next_cursor: null },
  }
}
async function enter(key = KEY) {
  await wrapper!.get('#create-booking-key').setValue(key)
  await vi.advanceTimersByTimeAsync(300)
  await flushPromises()
}
function failure(code: string, status: number, details?: unknown) {
  const config = { method: 'post', headers: new AxiosHeaders() } as InternalAxiosRequestConfig
  return new AxiosError('Request failed', undefined, config, undefined, {
    config,
    status,
    statusText: 'Conflict',
    headers: {},
    data: { code, message: 'Booking could not be added.', details },
  })
}
it('requires a valid full key before checking or adding a booking', async () => {
  const get = vi.spyOn(api, 'get'), post = vi.spyOn(api, 'post')
  render()
  await enter('CW2154654-2609')
  await wrapper!.get('form').trigger('submit')
  expect(wrapper!.text()).toContain('Enter a full booking number')
  expect(get).not.toHaveBeenCalled()
  expect(post).not.toHaveBeenCalled()
})
it('blocks an existing booking and lets the user open it', async () => {
  vi.spyOn(api, 'get').mockResolvedValue({ data: lookup() })
  const post = vi.spyOn(api, 'post')
  render()
  await enter('cw 2154654–rdu–2609')
  expect(wrapper!.text()).toContain('This booking already exists')
  expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  await wrapper!.get('form').trigger('submit')
  expect(post).not.toHaveBeenCalled()
  await wrapper!.get('.create-booking-duplicate button').trigger('click')
  expect(wrapper!.emitted('open')).toEqual([[KEY]])
})
it('adds a normalized new booking with supplier details for an Agent and opens it', async () => {
  vi.spyOn(api, 'get').mockResolvedValue({ data: missing() })
  const post = vi.spyOn(api, 'post').mockResolvedValue({ data: item(1) })
  render()
  await enter('cw 2154654–rdu–2609')
  expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  await wrapper!.get('#create-booking-supplier').setValue(' Example Hotel ')
  await wrapper!.get('form').trigger('submit')
  await flushPromises()
  expect(post).toHaveBeenCalledWith('/bookings', {
    booking_key: KEY,
    supplier_name: 'Example Hotel',
    supplier_type: 'hotel',
    confirm_new: false,
  }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  expect(wrapper!.emitted('open')).toEqual([[KEY]])
  expect(useUiStore().refreshVersion).toBe(1)
})
it('reuses supplier details for an existing folder without sending edits', async () => {
  vi.spyOn(api, 'get').mockResolvedValue({ data: missing(true) })
  const post = vi.spyOn(api, 'post').mockResolvedValue({ data: item(1) })
  render()
  await enter()
  expect(wrapper!.text()).toContain('Example Hotel')
  expect(wrapper!.find('#create-booking-supplier').exists()).toBe(false)
  await wrapper!.get('form').trigger('submit')
  await flushPromises()
  expect(post.mock.calls[0]?.[1]).toEqual({ booking_key: KEY, confirm_new: false })
})
it('collects supplier details when lookup falls back to another station folder', async () => {
  const differentStationKey = 'CW2154654-YUL-2609'
  vi.spyOn(api, 'get').mockResolvedValue({ data: {
    ...missing(true),
    booking_key: differentStationKey,
    display_key: 'CW 2154654-YUL-2609',
    suggestions: [{ booking_key: KEY, display_key: item().display_key,
      last_status: null, last_agent: null, updated_at: item().updated_at, distance: 1 }],
  } })
  const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {
    ...item(1), booking_key: differentStationKey, display_key: 'CW 2154654-YUL-2609', station_code: 'YUL',
  } })
  render()
  await enter(differentStationKey)
  expect(wrapper!.find('.create-booking-supplier').exists()).toBe(false)
  await wrapper!.get('#create-booking-supplier').setValue('Montreal Hotel')
  expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  await wrapper!.get('input[type="checkbox"]').setValue(true)
  await wrapper!.get('form').trigger('submit')
  await flushPromises()
  expect(post.mock.calls[0]?.[1]).toEqual({
    booking_key: differentStationKey, supplier_name: 'Montreal Hotel', supplier_type: 'hotel', confirm_new: true,
  })
  expect(wrapper!.emitted('open')).toEqual([[differentStationKey]])
})
it('blocks a duplicate created by another user after the availability check', async () => {
  vi.spyOn(api, 'get').mockResolvedValue({ data: missing(true) })
  const post = vi.spyOn(api, 'post').mockRejectedValue(failure('BOOKING_EXISTS', 409, { booking_key: KEY }))
  render()
  await enter()
  await wrapper!.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper!.text()).toContain('This booking already exists')
  expect(wrapper!.emitted('open')).toBeUndefined()
  expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  await wrapper!.get('form').trigger('submit')
  expect(post).toHaveBeenCalledTimes(1)
})
it('requires review of similar bookings before retrying a server confirmation response', async () => {
  vi.spyOn(api, 'get').mockResolvedValue({ data: missing(true) })
  const post = vi.spyOn(api, 'post')
    .mockRejectedValueOnce(failure('NEW_BOOKING_NEEDS_CONFIRM', 422, { suggestions: [{
      booking_key: 'CW2154655-RDU-2609', display_key: 'CW 2154655-RDU-2609',
      last_status: null, last_agent: null, updated_at: item().updated_at, distance: 1,
    }] }))
    .mockResolvedValueOnce({ data: item(1) })
  render()
  await enter()
  await wrapper!.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper!.text()).toContain('CW 2154655-RDU-2609')
  expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  await wrapper!.get('input[type="checkbox"]').setValue(true)
  await wrapper!.get('form').trigger('submit')
  await flushPromises()
  expect(post.mock.calls[1]?.[1]).toMatchObject({ confirm_new: true })
  expect(wrapper!.emitted('open')).toEqual([[KEY]])
})
