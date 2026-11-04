import { afterEach, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api/client'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { user } from '../test/bookingFixtures'
import BackgroundPushSettings from './BackgroundPushSettings.vue'
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
it('requests permission only after explicit opt-in, then registers and removes the owned subscription', async () => {
  setActivePinia(createPinia())
  useAuthStore().user = structuredClone(user)
  const permission = vi.fn().mockResolvedValue('granted'),
    unsubscribe = vi.fn().mockResolvedValue(true),
    subscribe = vi.fn()
  const subscription = {
    endpoint: 'https://fcm.googleapis.com/fcm/send/test',
    toJSON: () => ({ keys: { p256dh: 'public', auth: 'auth' } }),
    unsubscribe,
  }
  subscribe.mockResolvedValue(subscription)
  const getSubscription = vi.fn().mockResolvedValue(null),
    registration = { active: {}, pushManager: { getSubscription, subscribe } }
  vi.stubGlobal('isSecureContext', true)
  vi.stubGlobal('PushManager', function () {})
  vi.stubGlobal('Notification', { permission: 'default', requestPermission: permission })
  const original = Object.getOwnPropertyDescriptor(navigator, 'serviceWorker')
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: { getRegistration: vi.fn().mockResolvedValue(registration) },
  })
  vi.spyOn(api, 'get').mockResolvedValue({ data: { enabled: true, public_key: 'AA' } })
  const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { ok: true } }),
    remove = vi.spyOn(api, 'delete').mockResolvedValue({ data: { ok: true } })
  const wrapper = mount(BackgroundPushSettings, { global: { plugins: [i18n] } })
  await flushPromises()
  expect(permission).not.toHaveBeenCalled()
  await wrapper
    .findAll('button')
    .find((b) => b.text() === 'Enable background push')!
    .trigger('click')
  await flushPromises()
  expect(permission).toHaveBeenCalledOnce()
  expect(post).toHaveBeenCalledWith(
    '/push/subscribe',
    { endpoint: subscription.endpoint, keys: { p256dh: 'public', auth: 'auth' } },
    expect.anything(),
  )
  expect(useAuthStore().user?.settings?.web_push_enabled).toBe(true)
  getSubscription.mockResolvedValue(subscription)
  await wrapper
    .findAll('button')
    .find((b) => b.text() === 'Disable background push')!
    .trigger('click')
  await flushPromises()
  expect(remove).toHaveBeenCalledWith(
    '/push/subscribe',
    expect.objectContaining({ data: { endpoint: subscription.endpoint } }),
  )
  expect(unsubscribe).toHaveBeenCalledOnce()
  expect(useAuthStore().user?.settings?.web_push_enabled).toBe(false)
  wrapper.unmount()
  if (original) Object.defineProperty(navigator, 'serviceWorker', original)
  else delete (navigator as unknown as Record<string, unknown>).serviceWorker
})
