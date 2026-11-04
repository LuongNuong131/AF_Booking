export type HighlightPart = { text: string; match: boolean }
const fold = (value: string) =>
  value.normalize('NFD').replace(/\p{M}/gu, '').replace(/[đĐ]/g, 'd').toLowerCase()
export function noteHighlight(text: string, query: string): HighlightPart[] {
  const needle = fold(query.trim())
  if (!needle) return [{ text, match: false }]
  let normalized = '',
    offset = 0
  const starts: number[] = [],
    ends: number[] = []
  for (const char of text) {
    const value = fold(char)
    for (const c of value) {
      normalized += c
      for (let j = 0; j < c.length; j++) {
        starts.push(offset)
        ends.push(offset + char.length)
      }
    }
    if (!value && ends.length) ends[ends.length - 1] = offset + char.length
    offset += char.length
  }
  const result: HighlightPart[] = []
  let previous = 0,
    at = 0
  while ((at = normalized.indexOf(needle, at)) >= 0) {
    const start = starts[at]!,
      end = ends[at + needle.length - 1]!
    if (start > previous) result.push({ text: text.slice(previous, start), match: false })
    result.push({ text: text.slice(start, end), match: true })
    previous = end
    at += needle.length
  }
  if (previous < text.length) result.push({ text: text.slice(previous), match: false })
  return result.length ? result : [{ text, match: false }]
}
