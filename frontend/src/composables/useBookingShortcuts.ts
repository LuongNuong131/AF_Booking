import { inject, onScopeDispose, shallowRef, type InjectionKey } from 'vue'
import { useMagicKeys } from '@vueuse/core'
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
  const registry = inject(shortcutRegistryKey)
  const ui = useUiStore()
  const call = (action: () => unknown) => {
    try {
      void Promise.resolve(action()).catch(() =>
        ui.notify(i18n.global.t('errors.UNKNOWN'), 'error'),
      )
    } catch {
      ui.notify(i18n.global.t('errors.UNKNOWN'), 'error')
    }
  }
  useMagicKeys({
    passive: false,
    onEventFired(event) {
      if (
        event.type !== 'keydown' ||
        event.repeat ||
        event.defaultPrevented ||
        event.isComposing ||
        event.keyCode === 229 ||
        ui.shortcutHelp ||
        ui.taskModalOpen ||
        registry?.current.value?.enabled?.() === false
      )
        return
      const target = event.target instanceof HTMLElement ? event.target : null
      const editable = !!target?.closest(
        'input,textarea,select,[contenteditable="true"],[role="textbox"]',
      )
      if (event.key === '?' && !editable && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault()
        ui.shortcutHelp = true
        return
      }
      const context = registry?.current.value
      if (!context) return
      const input = context.input()
      const inInput = !!input && !!target && (input === target || input.contains(target))
      const inScope = !!context.scope?.()?.contains(target)
      if (editable && !inInput && !inScope) return
      if (
        event.key === '/' &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        (!editable || inInput)
      ) {
        event.preventDefault()
        input?.focus()
        return
      }
      if (
        event.altKey &&
        event.code === 'KeyT' &&
        !event.ctrlKey &&
        !event.metaKey &&
        context.task
      ) {
        event.preventDefault()
        call(context.task)
        return
      }
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.altKey) {
        event.preventDefault()
        call(context.save)
        return
      }
      if (event.altKey && !event.ctrlKey && !event.metaKey && /^Digit[1-5]$/.test(event.code)) {
        const status = [...context.statuses()].sort(
          (a, b) => a.sort_order - b.sort_order || a.id - b.id,
        )[Number(event.code.slice(-1)) - 1]
        if (status) {
          event.preventDefault()
          call(() => context.selectStatus(status.code))
        }
        return
      }
      if (
        event.key === 'Enter' &&
        inInput &&
        !event.shiftKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey
      ) {
        event.preventDefault()
        call(context.lookup)
      } else if (
        (event.key === 'Escape' && (!editable || inInput || (context.back && inScope))) ||
        (event.key === 'Backspace' &&
          inInput &&
          !(input as HTMLInputElement).value.trim() &&
          context.back)
      ) {
        event.preventDefault()
        call(context.back ?? context.clear)
        input?.focus()
      }
    },
  })
}
