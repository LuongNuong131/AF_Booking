import { watch } from 'vue'
import { useUiStore } from '../stores/ui'

// Future views can subscribe without replacing form values or blocking navigation.
export function useViewRefresh(load: () => unknown): () => void {
  const ui = useUiStore()
  return watch(
    () => ui.refreshVersion,
    () => {
      void load()
    },
  )
}
