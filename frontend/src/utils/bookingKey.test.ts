import { describe, expect, it } from 'vitest'
import cases from '../../../fixtures/booking-keys.json'
import { build_key, normalize, parse, to_display } from './bookingKey'

describe('shared Python/TypeScript booking keys', () => {
  it.each(cases)('$raw -> $kind', ({ raw, kind, key }) => {
    const result = parse(raw)
    if (kind === 'invalid') expect(result).toBeNull()
    else if (kind === 'partial') expect(result && 'normalized' in result && result.normalized).toBe(key)
    else {
      expect(result && 'key' in result && result.key).toBe(key)
      expect(to_display(key!)).toBe('CW 2154654-RDU-2609')
    }
  })
  it('limits length, strips controls only in normalize, and validates components', () => {
    expect(parse('x'.repeat(129))).toBeNull()
    expect(normalize('CW\u00002154654-RDU-2609')).toBe('CW2154654-RDU-2609')
    expect(build_key('CW2154654', 'RDU', '2609')).toBe('CW2154654-RDU-2609')
    expect(() => build_key('CW123', 'RDU', '2609')).toThrow()
  })
})
