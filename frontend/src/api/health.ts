import { api } from './client'
import { isApiError } from './errors'

export type DatabaseState = 'connected' | 'not_configured' | 'unavailable'
export interface ServiceState {
  api: 'online' | 'offline'
  database: DatabaseState
}

export async function checkServices(): Promise<ServiceState> {
  try {
    const response = await api.get<unknown>('/ready', {
      validateStatus: (status) => status === 200 || status === 503,
    })
    const body = response.data
    if (response.status === 200 && body && typeof body === 'object'
      && 'status' in body && body.status === 'ok'
      && 'database' in body && body.database === 'connected') {
      return { api: 'online', database: 'connected' }
    }
    if (response.status === 503 && isApiError(body) && body.code === 'SERVICE_BUSY') {
      const details = body.details
      if (details && typeof details === 'object' && !Array.isArray(details)) {
        const database = details.database
        if (database === 'not_configured' || database === 'unavailable') {
          return { api: 'online', database }
        }
      }
    }
    return { api: 'offline', database: 'unavailable' }
  } catch {
    return { api: 'offline', database: 'unavailable' }
  }
}
