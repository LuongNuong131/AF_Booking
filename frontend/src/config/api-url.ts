export function resolveApiBaseUrl(value: string | undefined, production: boolean): string {
  if (!value) {
    if (production) throw new Error('VITE_API_BASE_URL is required for production builds.')
    return 'http://localhost:8000/api/v1'
  }
  const url = new URL(value)
  if (
    !['http:', 'https:'].includes(url.protocol) ||
    url.username || url.password || url.search || url.hash
  ) throw new Error('VITE_API_BASE_URL must be an HTTP(S) URL without credentials, query, or fragment.')
  if (production && url.protocol !== 'https:') {
    throw new Error('VITE_API_BASE_URL must use HTTPS in production.')
  }
  if (url.pathname.replace(/\/$/, '') !== '/api/v1') {
    throw new Error('VITE_API_BASE_URL must end in /api/v1.')
  }
  return value.replace(/\/$/, '')
}
