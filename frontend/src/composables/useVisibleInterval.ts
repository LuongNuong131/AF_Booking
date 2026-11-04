import { onMounted, onScopeDispose } from 'vue'
export function useVisibleInterval(
  load: () => unknown,
  milliseconds: number,
  cancel: () => void = () => {},
) {
  let timer: ReturnType<typeof setTimeout> | undefined,
    disposed = false,
    generation = 0
  async function tick(ticket: number) {
    if (disposed || document.hidden || ticket !== generation) return
    await load()
    if (!disposed && !document.hidden && ticket === generation)
      timer = setTimeout(() => void tick(ticket), milliseconds)
  }
  function changed() {
    generation++
    clearTimeout(timer)
    if (document.hidden) cancel()
    else void tick(generation)
  }
  onMounted(() => {
    document.addEventListener('visibilitychange', changed)
    void tick(generation)
  })
  onScopeDispose(() => {
    disposed = true
    generation++
    clearTimeout(timer)
    cancel()
    document.removeEventListener('visibilitychange', changed)
  })
}
