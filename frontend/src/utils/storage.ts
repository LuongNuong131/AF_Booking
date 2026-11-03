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
): void {
  try {
    if (value === null) window[kind].removeItem(key)
    else window[kind].setItem(key, value)
  } catch {
    /* In-memory session still works when storage is unavailable. */
  }
}
