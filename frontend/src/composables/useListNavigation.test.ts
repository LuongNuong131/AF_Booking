import { effectScope, ref, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { expect, it, vi } from 'vitest'
import { useListNavigation } from './useListNavigation'
import { useShortcuts } from './useShortcuts'

it('uses roving focus, opens and invokes W/T/page only in its scope, and ignores typing', async () => {
  setActivePinia(createPinia())
  const root = document.createElement('div'),
    other = document.createElement('input')
  root.innerHTML =
    '<article data-nav-key="a" tabindex="0"></article><article data-nav-key="b" tabindex="-1"></article><textarea></textarea>'
  document.body.append(root, other)
  const scope = effectScope(),
    open = vi.fn(),
    watch = vi.fn(),
    task = vi.fn(),
    page = vi.fn()
  const nav = scope.run(() =>
    useListNavigation('test', ref(root), () => ['a', 'b'], {
      open,
      watch,
      task,
      page,
    }),
  )!
  const press = (target: HTMLElement, key: string) =>
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
  const first = root.querySelector<HTMLElement>('article')!
  first.focus()
  press(first, 'j')
  await nextTick()
  await nextTick()
  expect(document.activeElement?.getAttribute('data-nav-key')).toBe('b')
  expect(nav.tabindex(1)).toBe(0)
  const second = document.activeElement as HTMLElement
  press(second, 'Enter')
  press(second, 'w')
  press(second, 't')
  press(second, ']')
  press(second, '[')
  expect(open).toHaveBeenCalledWith(1)
  expect(watch).toHaveBeenCalledWith(1)
  expect(task).toHaveBeenCalledWith(1)
  expect(page.mock.calls).toEqual([[1], [-1]])
  const input = root.querySelector('textarea')!
  input.focus()
  for (const key of ['j', 'k', 'ArrowDown', 'Enter', 'w', 't', '[', ']']) press(input, key)
  expect(open).toHaveBeenCalledTimes(1)
  expect(watch).toHaveBeenCalledTimes(1)
  expect(task).toHaveBeenCalledTimes(1)
  other.focus()
  press(other, 'w')
  expect(watch).toHaveBeenCalledTimes(1)
  scope.stop()
  root.remove()
  other.remove()
})
it('warns in development for duplicate keys in the same scope and disposes them', () => {
  const warning = vi.spyOn(console, 'warn').mockImplementation(() => {}),
    a = effectScope(),
    b = effectScope()
  a.run(() => useShortcuts('duplicate', [{ key: 'w', run: () => {} }]))
  b.run(() => useShortcuts('duplicate', [{ key: 'w', run: () => {} }]))
  expect(warning).toHaveBeenCalledWith('Duplicate shortcut w in scope duplicate')
  a.stop()
  b.stop()
  warning.mockRestore()
})
