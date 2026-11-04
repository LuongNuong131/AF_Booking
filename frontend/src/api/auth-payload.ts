import type { LoginResponse, PublicUser } from '../types/api.generated'
const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value)
export function parseUser(value: unknown): PublicUser {
  if (
    !record(value) ||
    !Number.isSafeInteger(value.id) ||
    Number(value.id) <= 0 ||
    typeof value.username !== 'string' ||
    typeof value.full_name !== 'string' ||
    !['agent', 'qc', 'admin'].includes(String(value.role)) ||
    typeof value.is_active !== 'boolean' ||
    (value.must_change_password!==undefined && typeof value.must_change_password!=='boolean') ||
    !(value.settings === null || record(value.settings))
  )
    throw new Error('Invalid user response')
  return value as unknown as PublicUser
}
export function parseLogin(value: unknown): LoginResponse {
  if (
    !record(value) ||
    typeof value.access_token !== 'string' ||
    !value.access_token ||
    typeof value.expires_in !== 'number'
  )
    throw new Error('Invalid login response')
  return {
    access_token: value.access_token,
    expires_in: value.expires_in,
    user: parseUser(value.user),
    token_type: 'bearer',
  }
}
