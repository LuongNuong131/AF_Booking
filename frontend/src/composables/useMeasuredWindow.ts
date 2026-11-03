import {
  computed,
  ref,
  shallowRef,
  onScopeDispose,
  type Ref,
  type ComponentPublicInstance,
} from 'vue'
// Variable-height timeline rows: measure mounted rows, retain off-screen heights.
export function useMeasuredWindow<T extends { id: number }>(rows: Ref<T[]>, estimate = 190) {
  const top = ref(0),
    heights = shallowRef(new Map<number, number>())
  const active = computed(() => rows.value.length > 50)
  const offsets = computed(() => {
    const values = [0]
    for (const row of rows.value)
      values.push(values.at(-1)! + (heights.value.get(row.id) ?? estimate))
    return values
  })
  const start = computed(() =>
    active.value ? Math.max(0, offsets.value.findIndex((n) => n > top.value - 400) - 1) : 0,
  )
  const end = computed(() =>
    active.value
      ? Math.min(
          rows.value.length,
          offsets.value.findIndex((n) => n > top.value + 1100) < 0
            ? rows.value.length
            : offsets.value.findIndex((n) => n > top.value + 1100),
        )
      : rows.value.length,
  )
  const visible = computed(() =>
    rows.value.slice(start.value, end.value).map((row, i) => ({ row, index: start.value + i })),
  )
  const padding = computed(() =>
    active.value
      ? {
          paddingTop: `${offsets.value[start.value]}px`,
          paddingBottom: `${offsets.value.at(-1)! - offsets.value[end.value]!}px`,
        }
      : {},
  )
  const observer =
    typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver((entries) => {
          const next = new Map(heights.value)
          let changed = false
          for (const entry of entries) {
            const id = Number((entry.target as HTMLElement).dataset.rowId),
              height = entry.target.getBoundingClientRect().height
            if (height > 0 && next.get(id) !== height) {
              next.set(id, height)
              changed = true
            }
          }
          if (changed) heights.value = next
        })
  const elements = new Map<number, Element>()
  function measure(id: number, el: Element | ComponentPublicInstance | null) {
    const previous = elements.get(id)
    if (previous) observer?.unobserve(previous)
    if (el instanceof Element) {
      ;(el as HTMLElement).dataset.rowId = String(id)
      elements.set(id, el)
      observer?.observe(el)
    } else elements.delete(id)
  }
  function scroll(event: Event) {
    top.value = (event.target as HTMLElement).scrollTop
  }
  onScopeDispose(() => {
    observer?.disconnect()
    elements.clear()
  })
  return { active, visible, padding, measure, scroll }
}
