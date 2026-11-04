import { it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { usePwaStore } from '../stores/pwa'
import { i18n } from '../i18n'
import PwaUpdateBanner from './PwaUpdateBanner.vue'
it('keeps a waiting worker until the user clicks Reload', async () => {
  setActivePinia(createPinia())
  const store = usePwaStore(),
    postMessage = vi.fn()
  store.updateReady = true
  store.registration = { waiting: { postMessage } } as unknown as ServiceWorkerRegistration
  const wrapper = mount(PwaUpdateBanner, { global: { plugins: [i18n] } })
  expect(wrapper.text()).toContain('A new version is available. Reload')
  expect(postMessage).not.toHaveBeenCalled()
  await wrapper.get('button').trigger('click')
  expect(postMessage).toHaveBeenCalledWith({ type: 'SKIP_WAITING' })
  expect(store.reloading).toBe(true)
  wrapper.unmount()
})
it('keeps the current version when an active editor cannot persist its draft', async () => {
  setActivePinia(createPinia())
  const store = usePwaStore(),
    postMessage = vi.fn()
  store.updateReady = true
  store.registration = { waiting: { postMessage } } as unknown as ServiceWorkerRegistration
  window.addEventListener('booking:prepare-reload', (event) => event.preventDefault(), {
    once: true,
  })
  const wrapper = mount(PwaUpdateBanner, { global: { plugins: [i18n] } })
  await wrapper.get('button').trigger('click')
  expect(postMessage).not.toHaveBeenCalled()
  expect(store.reloading).toBe(false)
  wrapper.unmount()
})
