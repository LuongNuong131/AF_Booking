import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import { useRequest } from './useRequest'
import { useViewRefresh } from './useViewRefresh'
import { timeouts } from '../config/timeouts'
import type { Page } from '../types/api.generated'
export function usePagedApi<T>(
  path: () => string,
  filters: () => Record<string, unknown> = () => ({}),
) {
  const page = ref(1),
    request = useRequest(
      async ({ signal, timeoutMs }) =>
        (
          await api.get<Page<T>>(path(), {
            params: { ...filters(), page: page.value, size: 20 },
            signal,
            timeout: timeoutMs,
          })
        ).data,
      { timeoutMs: timeouts.list, retry: true },
    )
  const items = computed(() => request.data.value?.items ?? []),
    total = computed(() => request.data.value?.total ?? 0)
  async function load() {
    await request.run()
  }
  function apply() {
    if (page.value !== 1) page.value = 1
    else void load()
  }
  watch(
    path,
    () => {
      page.value = 1
      void load()
    },
    { immediate: true },
  )
  watch(page, load)
  useViewRefresh(load)
  return { page, request, items, total, load, apply }
}
