import { describe, expect, it } from 'vitest'
import { isApiError } from './errors'

describe('API error envelopes', () => {
  it('accepts typed errors with optional structured details', () => {
    expect(isApiError({ code: 'REQUEST_TIMEOUT', message: 'Please try again.' })).toBe(true)
    expect(isApiError({ code: 'VERSION_CONFLICT', message: 'Review the latest note.',
      details: { version: 2, last_agent: null } })).toBe(true)
  })
  it.each([null, 'error', [], {}, { detail: 'Unauthorized' },
    { error: { code: 'REQUEST_TIMEOUT', message: 'Try again.' } },
    { code: 'UNKNOWN_CODE', message: 'Try again.' }, { code: 'UNAUTHORIZED', message: '' },
  ])('rejects malformed or incompatible envelopes: %j', (value) => {
    expect(isApiError(value)).toBe(false)
  })
})
