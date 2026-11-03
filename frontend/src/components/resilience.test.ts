import { afterEach, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { i18n } from '../i18n'
import { useRequest } from '../composables/useRequest'
import { installRouteResilience } from '../composables/useRouteResilience'
import { useUiStore } from '../stores/ui'
import RequestStatus from './RequestStatus.vue'
import ErrorBoundary from './ErrorBoundary.vue'

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})
it('keeps input and focus through slow, timeout and retry; releases loading buttons', async () => {
  vi.useFakeTimers()
  let request!: ReturnType<typeof useRequest<string>>
  const Harness = defineComponent({
    setup() {
      const value = ref('CW 2154654-RDU-2609')
      request = useRequest(() => new Promise<string>(() => {}), {
        timeoutMs: 8000,
        slowMs: 3000,
      })
      return () =>
        h('div', [
          h('input', {
            value: value.value,
            onInput: (event: Event) => {
              value.value = (event.target as HTMLInputElement).value
            },
          }),
          h('button', { disabled: request.pending.value, onClick: () => request.run() }, 'Submit'),
          h(RequestStatus, {
            state: request.state.value,
            error: request.error.value,
            onRetry: () => request.run(),
          }),
        ])
    },
  })
  const wrapper = mount(Harness, {
    attachTo: document.body,
    global: { plugins: [i18n] },
  })
  const input = wrapper.get('input')
  ;(input.element as HTMLElement).focus()
  void request.run()
  await vi.advanceTimersByTimeAsync(3000)
  await nextTick()
  expect(wrapper.text()).toContain('Still working…')
  expect(document.activeElement).toBe(input.element)
  await input.setValue('CW 9999999-YUL-2610')
  await vi.advanceTimersByTimeAsync(5000)
  await nextTick()
  expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
  expect(input.element.value).toBe('CW 9999999-YUL-2610')
  const retry = wrapper.findAll('button').find((button) => button.text() === 'Retry')!
  await retry.trigger('mousedown')
  await retry.trigger('click')
  expect(document.activeElement).toBe(input.element)
  expect(input.element.value).toBe('CW 9999999-YUL-2610')
  expect(request.state.value).toBe('loading')
  wrapper.unmount()
})
it('contains a section render failure and allows an independent retry', async () => {
  let broken = true
  const Child = defineComponent({
    setup: () => () => {
      if (broken) throw new Error('Test render failure')
      return h('p', 'Recovered')
    },
  })
  const wrapper = mount(
    defineComponent({
      setup: () => () =>
        h('main', [
          h('input', { 'aria-label': 'Other section' }),
          h(ErrorBoundary, {}, { default: () => h(Child) }),
        ]),
    }),
    { global: { plugins: [i18n], config: { warnHandler: () => {} } } },
  )
  await nextTick()
  expect(wrapper.get('[role="alert"]').text()).toContain('This section could not be loaded.')
  expect(wrapper.find('input').exists()).toBe(true)
  broken = false
  await wrapper.get('button').trigger('click')
  expect(wrapper.text()).toContain('Recovered')
  wrapper.unmount()
})
it('ends route loading after 20 seconds and refreshes after a minute hidden', async () => {
  vi.useFakeTimers()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { render: () => null } },
      { path: '/slow', component: () => new Promise(() => {}) },
    ],
  })
  const pinia = createPinia(),
    ui = useUiStore(pinia)
  const stop = installRouteResilience(router, pinia)
  await router.push('/')
  void router.push('/slow')
  await vi.advanceTimersByTimeAsync(20000)
  expect(ui.routeLoading).toBe(false)
  expect(ui.routeFailed).toBe(true)
  expect(ui.pendingPath).toBe('/slow')
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
  document.dispatchEvent(new Event('visibilitychange'))
  await vi.advanceTimersByTimeAsync(60000)
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  document.dispatchEvent(new Event('visibilitychange'))
  expect(ui.refreshVersion).toBe(1)
  expect(ui.refreshReason).toBe('visible')
  stop()
})
