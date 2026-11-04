export function sentryOrigin(dsn?: string): string | null {
  if (!dsn?.trim()) return null
  const url = new URL(dsn)
  if (
    url.protocol !== 'https:' ||
    !url.username ||
    url.password ||
    !/^\/[0-9]+\/?$/.test(url.pathname) ||
    url.search ||
    url.hash
  )
    throw new Error('VITE_SENTRY_DSN must be a valid public HTTPS project DSN.')
  return url.origin
}
