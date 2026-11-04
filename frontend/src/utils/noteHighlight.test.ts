import { it, expect } from 'vitest'
import { noteHighlight } from './noteHighlight'
it('marks Vietnamese text case/diacritic-insensitively without changing the source', () => {
  const value = 'Hỏi KHÁCH SẠN lần hai',
    parts = noteHighlight(value, 'khach san')
  expect(parts.filter((p) => p.match).map((p) => p.text)).toEqual(['KHÁCH SẠN'])
  expect(parts.map((p) => p.text).join('')).toBe(value)
})
it('preserves emoji, decomposed accents and repeated matches', () => {
  const value = '✈️😀 khách sạn — khách sạn',
    parts = noteHighlight(value, 'khách sạn')
  expect(parts.map((p) => p.text).join('')).toBe(value)
  expect(parts.filter((p) => p.match).map((p) => p.text)).toEqual(['khách sạn', 'khách sạn'])
})
it('keeps literal markup as plain text segments', () => {
  const text = '<img src=x onerror="alert(1)">khách sạn'
  const parts = noteHighlight(text, 'khách sạn')
  expect(parts[0]).toEqual({ text: '<img src=x onerror="alert(1)">', match: false })
})
