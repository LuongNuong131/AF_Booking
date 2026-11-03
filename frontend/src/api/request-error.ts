import axios from 'axios'
import { i18n } from '../i18n'
import { isApiError, parseRetryAfter, type RequestFailure } from './errors'

export function normalizeRequestError(error: unknown): RequestFailure {
  if (axios.isAxiosError(error)) {
    const body: unknown = error.response?.data
    const common = {
      status: error.response?.status,
      method: error.config?.method?.toUpperCase(),
      retryAfterMs: parseRetryAfter(error.response?.headers?.['retry-after']),
    }
    if (isApiError(body))
      return { ...common, code: body.code, message: body.message, details: body.details }
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT')
      return { ...common, code: 'REQUEST_TIMEOUT', message: '' }
    if (axios.isCancel(error)) return { ...common, code: 'CANCELLED', message: '' }
    if (!error.response) return { ...common, code: 'NETWORK_ERROR', message: '', network: true }
    return { ...common, code: `HTTP_${error.response.status}`, message: '' }
  }
  return { code: 'UNKNOWN', message: '' }
}

export function errorMessage(error: RequestFailure | null): string {
  if (!error) return ''
  const key = `errors.${error.code}`
  if (i18n.global.te(key)) return i18n.global.t(key)
  return error.message || i18n.global.t('errors.UNKNOWN')
}
