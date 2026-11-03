import { shallowRef, ref } from 'vue'
export const apiMeasurements = shallowRef<{ path: string; timing: string }[]>([])
export const realtimeEvents = ref(0)
export function recordApi(path: string, timing: unknown) {
  if (import.meta.env.DEV && typeof timing === 'string')
    apiMeasurements.value = [{ path: path.split('?')[0]!, timing }, ...apiMeasurements.value].slice(
      0,
      8,
    )
}
