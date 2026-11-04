import { it, expect, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { useVisibleInterval } from './useVisibleInterval'
it('refreshes only while visible and mounted, cancels hiding and does not duplicate timers', async () => {
  vi.useFakeTimers()
  let hidden = false
  const descriptor = Object.getOwnPropertyDescriptor(document, 'hidden')
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
  const load = vi.fn().mockResolvedValue(undefined),
    cancel = vi.fn()
  const wrapper = mount(
    defineComponent({
      setup() {
        useVisibleInterval(load, 15000, cancel)
        return () => h('div')
      },
    }),
  )
  await flushPromises()
  expect(load).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(15000)
  expect(load).toHaveBeenCalledTimes(2)
  hidden = true
  document.dispatchEvent(new Event('visibilitychange'))
  expect(cancel).toHaveBeenCalledOnce()
  await vi.advanceTimersByTimeAsync(60000)
  expect(load).toHaveBeenCalledTimes(2)
  hidden = false
  document.dispatchEvent(new Event('visibilitychange'))
  await flushPromises()
  expect(load).toHaveBeenCalledTimes(3)
  wrapper.unmount()
  await vi.advanceTimersByTimeAsync(60000)
  expect(load).toHaveBeenCalledTimes(3)
  if (descriptor) Object.defineProperty(document, 'hidden', descriptor)
  else delete (document as unknown as Record<string, unknown>).hidden
  vi.useRealTimers()
})
