import { ERROR_CODES, type ApiError } from '../types/api.generated'

const errorCodes = new Set<string>(ERROR_CODES)

export function isApiError(value: unknown): value is ApiError {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const error = value as Record<string, unknown>
  return (
    typeof error.code === 'string' &&
    errorCodes.has(error.code) &&
    typeof error.message === 'string' &&
    error.message.length > 0
  )
}

export interface RequestFailure {
  code: string
  message: string
  status?: number
  method?: string
  details?: unknown
  network?: boolean
  retryAfterMs?: number
}

export function parseRetryAfter(value: unknown, now = Date.now()): number | undefined {
  if (typeof value !== 'string' && typeof value !== 'number') return undefined
  const seconds = Number(value)
  if (String(value).trim() && Number.isFinite(seconds) && seconds >= 0)
    return Math.ceil(seconds * 1000)
  const at = Date.parse(String(value))
  return Number.isFinite(at) ? Math.max(0, at - now) : undefined
}
