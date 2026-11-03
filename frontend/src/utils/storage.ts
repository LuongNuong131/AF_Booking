export function readStorage(kind: 'localStorage' | 'sessionStorage', key: string): string | null {
  try {
    return window[kind].getItem(key)
  } catch {
    return null
  }
}
export function writeStorage(
  kind: 'localStorage' | 'sessionStorage',
  key: string,
  value: string | null,
): boolean {
  try {
    if (value === null) window[kind].removeItem(key)
    else window[kind].setItem(key, value)
    return true
  } catch {
    // Auth can continue in memory; draft/theme callers can report failed persistence.
    return false
  }
}
