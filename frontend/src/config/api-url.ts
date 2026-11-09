function configured(value: string | undefined): string | undefined {
  return value?.trim() || undefined
}

export function resolveApiBaseUrl(value: string | undefined, production: boolean): string {
  value = configured(value)
  if (!value) {
    if (production)
      throw new Error(
        'VITE_API_URL is required for production. Set it in Vercel Project Settings > Environment Variables to https://YOUR-API.onrender.com/api/v1, then redeploy. VITE_API_BASE_URL remains a fallback alias.',
      )
    return 'http://localhost:8000/api/v1'
  }
  let url: URL
  try {
    url = new URL(value)
  } catch {
    throw new Error('VITE_API_URL must be a valid HTTP(S) API URL.')
  }
  if (
    !['http:', 'https:'].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new Error('VITE_API_URL must be an HTTP(S) URL without credentials, query, or fragment.')
  }
  if (production && url.protocol !== 'https:')
    throw new Error('VITE_API_URL must use HTTPS in production.')
  if (url.pathname.replace(/\/$/, '') !== '/api/v1')
    throw new Error('VITE_API_URL must end in /api/v1.')
  return url.toString().replace(/\/$/, '')
}

export function resolveWsUrl(
  value: string | undefined,
  apiUrl: string,
  production: boolean,
): string {
  let url: URL
  try {
    url = new URL(configured(value) ?? `${apiUrl.replace(/^http/, 'ws')}/ws`)
  } catch {
    throw new Error('VITE_WS_URL must be a valid WebSocket URL.')
  }
  if (
    !['ws:', 'wss:'].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname.replace(/\/$/, '') !== '/api/v1/ws'
  ) {
    throw new Error('VITE_WS_URL must end in /api/v1/ws without credentials, query, or fragment.')
  }
  if (production && url.protocol !== 'wss:')
    throw new Error('VITE_WS_URL must use WSS in production.')
  return url.toString().replace(/\/$/, '')
}

export function resolveEndpoints(
  env: {
    VITE_API_URL?: string
    VITE_API_BASE_URL?: string
    VITE_WS_URL?: string
  },
  production: boolean,
) {
  const apiUrl = resolveApiBaseUrl(
    configured(env.VITE_API_URL) ?? env.VITE_API_BASE_URL,
    production,
  )
  return { apiUrl, wsUrl: resolveWsUrl(env.VITE_WS_URL, apiUrl, production) }
}
