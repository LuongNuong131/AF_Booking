import axios from 'axios'
import { timeouts } from '../config/timeouts'
import { resolveEndpoints } from '../config/api-url'
import { isApiError } from './errors'
import { sessionHandlers } from './session'

export const endpoints = resolveEndpoints(import.meta.env, import.meta.env.PROD)
export const api = axios.create({
  baseURL: endpoints.apiUrl,
  timeout: timeouts.list,
  headers: { Accept: 'application/json' },
})

api.interceptors.request.use((config) => {
  const identity = sessionHandlers.identity()
  config.sessionIdentity = identity
  if (!config.skipAuth && identity.token)
    config.headers.set('Authorization', `Bearer ${identity.token}`)
  return config
})
api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && !error.config?.skipAuth) {
      const sent = error.config?.sessionIdentity
      const current = sessionHandlers.identity()
      // A delayed 401 from a previous login must never terminate the newer session.
      if (sent?.token && sent.token === current.token && sent.epoch === current.epoch) {
        if (error.response?.status === 401) {
          const body = error.response.data
          sessionHandlers.unauthorized(
            isApiError(body) && body.code === 'SESSION_REPLACED'
              ? 'SESSION_REPLACED'
              : 'UNAUTHORIZED',
          )
        } else if (error.response?.status === 403) sessionHandlers.forbidden()
      }
    }
    return Promise.reject(error)
  },
)
