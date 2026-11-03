import { expect, it, vi } from 'vitest'
import { defineComponent, h, provide } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import {
  createShortcutRegistry,
  shortcutRegistryKey,
  useBookingShortcuts,
  useWorkspaceShortcuts,
} from './useBookingShortcuts'
import { useUiStore } from '../stores/ui'
import type { Status } from '../types/api.generated'

it('scopes shortcuts to the booking input, ignores IME/unrelated fields, and reserves Ctrl+K', () => {
  const lookup = vi.fn(),
    save = vi.fn(),
    clear = vi.fn(),
    selectStatus = vi.fn()
  const input = document.createElement('input'),
    other = document.createElement('textarea')
  document.body.append(input, other)
  const registry = createShortcutRegistry(),
    pinia = createPinia()
  const Child = defineComponent({
    setup() {
      useWorkspaceShortcuts()
      useBookingShortcuts({
        input: () => input,
        lookup,
        save,
        clear,
        selectStatus,
        statuses: () =>
          [
            { id: 2, code: 'SECOND', sort_order: 20 },
            { id: 1, code: 'FIRST', sort_order: 10 },
          ] as Status[],
      })
      return () => h('div')
    },
  })
  const wrapper = mount(
    defineComponent({
      setup() {
        provide(shortcutRegistryKey, registry)
        return () => h(Child)
      },
    }),
    { global: { plugins: [pinia] } },
  )
  const press = (target: HTMLElement, key: string, init: KeyboardEventInit = {}) => {
    const event = new KeyboardEvent('keydown', {
      key,
      bubbles: true,
      cancelable: true,
      ...init,
    })
    target.dispatchEvent(event)
    return event
  }
  press(document.body, '/')
  expect(document.activeElement).toBe(input)
  press(input, 'Enter')
  press(input, 'Enter', { ctrlKey: true })
  press(input, '1', { code: 'Digit1', altKey: true })
  expect(lookup).toHaveBeenCalledTimes(1)
  expect(save).toHaveBeenCalledTimes(1)
  expect(selectStatus).toHaveBeenCalledWith('FIRST')
  press(input, 'Escape')
  expect(clear).toHaveBeenCalledTimes(1)
  other.focus()
  expect(press(other, '/', {}).defaultPrevented).toBe(false)
  press(other, 'Enter', { ctrlKey: true })
  press(input, 'Enter', { isComposing: true })
  expect(save).toHaveBeenCalledTimes(1)
  expect(lookup).toHaveBeenCalledTimes(1)
  expect(press(document.body, 'k', { ctrlKey: true }).defaultPrevented).toBe(false)
  press(document.body, '?')
  expect(useUiStore(pinia).shortcutHelp).toBe(true)
  wrapper.unmount()
  expect(registry.current.value).toBeNull()
  input.remove()
  other.remove()
})
