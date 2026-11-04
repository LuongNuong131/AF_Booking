import { onScopeDispose } from 'vue'

export interface Shortcut {
  key: string
  run: (event: KeyboardEvent) => unknown
  allowInput?: boolean
}
const entries: Array<{
  scope: string
  root?: () => HTMLElement | null
  enabled?: () => boolean
  bindings: Shortcut[]
}> = []
export const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  !!target.closest(
    'input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"]',
  )
export function matchesShortcut(event: KeyboardEvent, key: string) {
  const parts = key.toLowerCase().split('+')
  const last = parts.pop()!
  return (
    event.key.toLowerCase() === last &&
    (parts.includes('mod') ? event.ctrlKey || event.metaKey : !event.ctrlKey && !event.metaKey) &&
    event.altKey === parts.includes('alt') &&
    (!event.shiftKey || last === '?' || parts.includes('shift'))
  )
}
function dispatch(event: KeyboardEvent) {
  if (event.defaultPrevented || event.repeat || event.isComposing || event.keyCode === 229) return
  const ordered = [...entries].reverse().sort((a, b) => Number(!!b.root) - Number(!!a.root))
  for (const entry of ordered) {
    if (
      entry.enabled?.() === false ||
      (entry.root && !(event.target instanceof Node && entry.root()?.contains(event.target)))
    )
      continue
    const binding = entry.bindings.find(
      (b) => matchesShortcut(event, b.key) && (b.allowInput || !isTyping(event.target)),
    )
    if (!binding) continue
    if (binding.run(event) !== false) {
      event.preventDefault()
      return
    }
  }
}
export function useShortcuts(
  scope: string,
  bindings: Shortcut[],
  options: { root?: () => HTMLElement | null; enabled?: () => boolean } = {},
) {
  if (import.meta.env.DEV)
    for (const binding of bindings) {
      if (entries.some((e) => e.scope === scope && e.bindings.some((b) => b.key === binding.key)))
        console.warn(`Duplicate shortcut ${binding.key} in scope ${scope}`)
    }
  const entry = { scope, bindings, ...options }
  if (!entries.length) window.addEventListener('keydown', dispatch)
  entries.push(entry)
  onScopeDispose(() => {
    const i = entries.indexOf(entry)
    if (i >= 0) entries.splice(i, 1)
    if (!entries.length) window.removeEventListener('keydown', dispatch)
  })
}
