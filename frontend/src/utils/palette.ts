export function fuzzyScore(query: string, label: string): number {
  const normalize = (s: string) =>
    s
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
  const q = normalize(query.trim()),
    text = normalize(label)
  if (!q) return 0
  const exact = text.indexOf(q)
  if (exact >= 0) return 1000 - exact
  let position = 0,
    gaps = 0
  for (const ch of q) {
    const found = text.indexOf(ch, position)
    if (found < 0) return -1
    gaps += found - position
    position = found + 1
  }
  return 500 - gaps
}
export function commandNames(role: string) {
  return [
    'home',
    'summary',
    'profile',
    ...(role === 'admin' ? ['admin'] : []),
    ...(['admin', 'qc'].includes(role) ? ['reports', 'export'] : []),
    'theme',
    'logout',
    'notes',
  ]
}
