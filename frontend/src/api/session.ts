export interface SessionIdentity {
  token: string | null
  epoch: number
}
interface SessionHandlers {
  identity: () => SessionIdentity
  unauthorized: (code: 'UNAUTHORIZED' | 'SESSION_REPLACED') => void
  forbidden: () => void
}
const empty: SessionHandlers = {
  identity: () => ({ token: null, epoch: 0 }),
  unauthorized: () => {},
  forbidden: () => {},
}
let handlers = empty
export function configureApiSession(value: SessionHandlers): () => void {
  handlers = value
  return () => {
    if (handlers === value) handlers = empty
  }
}
export const sessionHandlers = {
  identity: () => handlers.identity(),
  unauthorized: (code: 'UNAUTHORIZED' | 'SESSION_REPLACED') => handlers.unauthorized(code),
  forbidden: () => handlers.forbidden(),
}

declare module 'axios' {
  interface AxiosRequestConfig {
    skipAuth?: boolean
    sessionIdentity?: SessionIdentity
  }
}
