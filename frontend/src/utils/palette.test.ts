import { it, expect } from 'vitest'
import { fuzzyScore, commandNames } from './palette'
it('ranks exact prefixes over subsequences, ignores accents, and rejects missing letters', () => {
  expect(fuzzyScore('summary', 'Go to Summary')).toBeGreaterThan(
    fuzzyScore('smry', 'Go to Summary'),
  )
  expect(fuzzyScore('hotel', 'Hôtel')).toBe(1000)
  expect(fuzzyScore('xyz', 'Go to Home')).toBe(-1)
})
it('only offers admin and report/export commands to the permitted roles', () => {
  expect(commandNames('agent')).not.toContain('admin')
  expect(commandNames('agent')).not.toContain('export')
  expect(commandNames('qc')).toContain('export')
  expect(commandNames('qc')).not.toContain('admin')
  expect(commandNames('admin')).toContain('admin')
})
