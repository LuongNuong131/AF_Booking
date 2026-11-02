import { api } from './client'

export type DatabaseState = 'connected' | 'not_configured' | 'unavailable'
export interface ServiceState {
  api: 'online' | 'offline'
  database: DatabaseState
}

export async function checkServices(): Promise<ServiceState> {
  try {
    const response = await api.get<{ status: string; database: DatabaseState }>('/ready', {
      validateStatus: (status) => status === 200 || status === 503,
    })
    const database = response.data.database
    if (!['connected', 'not_configured', 'unavailable'].includes(database)) {
      throw new Error('Unexpected readiness response')
    }
    return { api: 'online', database }
  } catch {
    return { api: 'offline', database: 'unavailable' }
  }
}
