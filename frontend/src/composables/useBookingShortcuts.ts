import { inject, onScopeDispose, shallowRef, type InjectionKey } from 'vue'
import { useShortcuts, isTyping } from './useShortcuts'
import { useUiStore } from '../stores/ui'
import { i18n } from '../i18n'
import type { Status } from '../types/api.generated'

export interface BookingShortcutContext {
  enabled?: () => boolean
  input: () => HTMLElement | null
  scope?: () => HTMLElement | null
  lookup: () => unknown
  save: () => unknown
  task?: () => unknown
  clear: () => unknown
  back?: () => unknown
  statuses: () => Status[]
  selectStatus: (code: string) => unknown
}
export function createShortcutRegistry() {
  const current = shallowRef<BookingShortcutContext | null>(null)
  return {
    current,
    register(value: BookingShortcutContext) {
      current.value = value
      return () => {
        if (current.value === value) current.value = null
      }
    },
  }
}
export const shortcutRegistryKey: InjectionKey<ReturnType<typeof createShortcutRegistry>> =
  Symbol('booking-shortcuts')
export function useBookingShortcuts(context: BookingShortcutContext): void {
  const registry = inject(shortcutRegistryKey)
  if (!registry) throw new Error('Booking shortcuts require the application shortcut registry.')
  onScopeDispose(registry.register(context))
}
export function useWorkspaceShortcuts(): void {
  const registry = inject(shortcutRegistryKey),
    ui = useUiStore()
  const context = () => registry?.current.value
  const call = (fn: (() => unknown) | undefined) => {
    if (!fn) return false
    try {
      void Promise.resolve(fn()).catch(() => ui.notify(i18n.global.t('errors.UNKNOWN'), 'error'))
    } catch {
      ui.notify(i18n.global.t('errors.UNKNOWN'), 'error')
    }
  }
  const inInput = (e: KeyboardEvent) => {
    const input = context()?.input()
    return !!input && e.target instanceof Node && (input === e.target || input.contains(e.target))
  }
  const inScope = (e: KeyboardEvent) =>
    e.target instanceof Node && !!context()?.scope?.()?.contains(e.target)
  useShortcuts(
    'workspace',
    [
      {
        key: 'mod+k',
        allowInput: true,
        run: () => {
          ui.paletteOpen = true
        },
      },
      {
        key: '?',
        run: () => {
          ui.shortcutHelp = true
        },
      },
      { key: '/', run: () => call(() => context()?.input()?.focus()) },
      {
        key: 'alt+t',
        allowInput: true,
        run: (e) =>
          !isTyping(e.target) || inInput(e) || inScope(e) ? call(context()?.task) : false,
      },
      {
        key: 'mod+Enter',
        allowInput: true,
        run: (e) =>
          !isTyping(e.target) || inInput(e) || inScope(e) ? call(context()?.save) : false,
      },
      ...[1, 2, 3, 4, 5].map((n) => ({
        key: `alt+${n}`,
        allowInput: true,
        run: (e: KeyboardEvent) => {
          if (isTyping(e.target) && !inInput(e) && !inScope(e)) return false
          const c = context(),
            status =
              c &&
              [...c.statuses()].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)[n - 1]
          return status ? call(() => c!.selectStatus(status.code)) : false
        },
      })),
      {
        key: 'Enter',
        allowInput: true,
        run: (e) => (inInput(e) ? call(context()?.lookup) : false),
      },
      {
        key: 'Escape',
        allowInput: true,
        run: (e) =>
          !isTyping(e.target) || inInput(e) || (context()?.back && inScope(e))
            ? call(context()?.back ?? context()?.clear)
            : false,
      },
      {
        key: 'Backspace',
        allowInput: true,
        run: (e) =>
          inInput(e) && !(context()?.input() as HTMLInputElement)?.value.trim()
            ? call(context()?.back)
            : false,
      },
    ],
    {
      enabled: () =>
        !ui.paletteOpen &&
        !ui.shortcutHelp &&
        !ui.taskModalOpen &&
        context()?.enabled?.() !== false,
    },
  )
}
