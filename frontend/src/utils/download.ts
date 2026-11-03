import { api } from '../api/client'
import type { RequestContext } from '../composables/useRequest'
import { isAxiosError } from 'axios'
export async function downloadDaily(ctx: RequestContext, params: Record<string, string>) {
  try {
    const response = await api.get<Blob>('/export/daily', {
      params,
      responseType: 'blob',
      signal: ctx.signal,
      timeout: ctx.timeoutMs,
    })
    return response.data
  } catch (error) {
    if (
      isAxiosError(error) &&
      error.response?.data instanceof Blob &&
      error.response.data.size < 65536
    ) {
      try {
        error.response.data = JSON.parse(await error.response.data.text())
      } catch {
        /* Keep the sanitized HTTP failure if it is not JSON. */
      }
    }
    throw error
  }
}
export function saveDownload(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob),
    link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
