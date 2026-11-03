import { expect, it } from 'vitest'
import cases from '../../../fixtures/search-queries.json'
import { classifyQuery, normalizeSearch } from './searchQuery'
it.each(cases)('classifies $input using the backend fixture', ({ input, kind }) => {
  expect(classifyQuery(input, ['YUL']).kind).toBe(kind)
})
it('uses configurable known stations and preserves supplier word boundaries', () => {
  expect(classifyQuery('XX', ['XX'], '[A-Z]{2}').kind).toBe('station')
  expect(classifyQuery('XX 2608', [], '[A-Z]{2}').kind).toBe('station_period')
  expect(classifyQuery('ABC').kind).toBe('text')
  expect(normalizeSearch(' double   tree ')).toBe('DOUBLE TREE')
})
