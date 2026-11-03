export function safeRedirect(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !value.startsWith('/') ||
    value.startsWith('//') ||
    value.includes('\\') ||
    /[\p{Cc}\p{Cf}]/u.test(value)
  )
    return '/'
  const pathname = value.split(/[?#]/, 1)[0]
  return pathname === '/login' ? '/' : value
}
