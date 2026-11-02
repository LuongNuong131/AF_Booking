import { ERROR_CODES, type ApiError } from '../types/api.generated'

const errorCodes = new Set<string>(ERROR_CODES)

export function isApiError(value: unknown): value is ApiError {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const error = value as Record<string, unknown>
  return typeof error.code === 'string' && errorCodes.has(error.code)
    && typeof error.message === 'string' && error.message.length > 0
}
