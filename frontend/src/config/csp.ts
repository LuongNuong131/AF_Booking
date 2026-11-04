export function buildCsp(apiUrl: string, wsUrl: string): string {
  const api = new URL(apiUrl),
    ws = new URL(wsUrl)
  if (
    api.protocol !== 'https:' ||
    ws.protocol !== 'wss:' ||
    api.username ||
    api.password ||
    ws.username ||
    ws.password
  )
    throw new Error('CSP requires public HTTPS API and WSS WebSocket origins.')
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src 'self' ${api.origin} ${ws.origin}`,
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "frame-src 'none'",
    "worker-src 'self'",
    "manifest-src 'self'",
  ].join('; ')
}
