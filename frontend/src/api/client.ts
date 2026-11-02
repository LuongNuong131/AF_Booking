import axios from 'axios'
import { timeouts } from '../config/timeouts'
import { resolveApiBaseUrl } from '../config/api-url'

// Validate at runtime too: an incorrect deployment must not silently use localhost.
export const api = axios.create({
  baseURL: resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL, import.meta.env.PROD),
  timeout: timeouts.api,
  headers: { Accept: 'application/json' },
})
