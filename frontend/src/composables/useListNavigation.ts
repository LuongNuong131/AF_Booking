import { ref, watch, nextTick, type Ref } from 'vue'
import { useShortcuts } from './useShortcuts'
import { useUiStore } from '../stores/ui'

export function useListNavigation(
  scope: string,
  root: Ref<HTMLElement | null>,
  keys: () => Array<string | number>,
  actions: {
    open: (index: number) => unknown
    watch?: (index: number) => unknown
    task?: (index: number) => unknown
    page?: (delta: number) => unknown
    reveal?: (index: number) => unknown
  },
) {
  const active = ref(0),
    ui = useUiStore()
  watch(keys, (values) => {
    active.value = Math.min(active.value, Math.max(0, values.length - 1))
  })
  function selected(i: number) {
    active.value = i
  }
  async function move(delta: number) {
    if (!keys().length) return false
    active.value = Math.max(0, Math.min(keys().length - 1, active.value + delta))
    actions.reveal?.(active.value)
    await nextTick()
    Array.from(root.value?.querySelectorAll<HTMLElement>('[data-nav-key]') ?? [])
      .find((e) => e.dataset.navKey === String(keys()[active.value]))
      ?.focus()
  }
  const call = (fn: ((index: number) => unknown) | undefined) => {
    if (!fn || !keys().length) return false
    void fn(active.value)
  }
  useShortcuts(
    scope,
    [
      ...['j', 'ArrowDown'].map((key) => ({ key, run: () => move(1) })),
      ...['k', 'ArrowUp'].map((key) => ({ key, run: () => move(-1) })),
      {
        key: 'Enter',
        run: (e) => {
          const target = e.target as HTMLElement
          if (!target?.hasAttribute('data-nav-key')) return false
          return call(actions.open)
        },
      },
      { key: 'w', run: () => call(actions.watch) },
      { key: 't', run: () => call(actions.task) },
      { key: '[', run: () => (actions.page ? actions.page(-1) : false) },
      { key: ']', run: () => (actions.page ? actions.page(1) : false) },
    ],
    {
      root: () => root.value,
      enabled: () => !ui.paletteOpen && !ui.shortcutHelp && !ui.taskModalOpen,
    },
  )
  return {
    active,
    selected,
    tabindex: (i: number) => (i === active.value ? 0 : -1),
  }
}
