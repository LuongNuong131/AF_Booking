import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { resolveEndpoints } from '../src/config/api-url.ts'
import { buildCsp } from '../src/config/csp.ts'
const env = { ...process.env, VITE_API_URL: process.argv[2] || process.env.VITE_API_URL }
const { apiUrl, wsUrl } = resolveEndpoints(env, true)
const file = fileURLToPath(new URL('../vercel.json', import.meta.url))
const config = JSON.parse(readFileSync(file, 'utf8'))
const global = config.headers.find((row) => row.source === '/(.*)')
const existing = global.headers.find(
  (row) => row.key.toLowerCase() === 'content-security-policy',
)
const value = buildCsp(apiUrl, wsUrl, process.env.VITE_SENTRY_DSN)
if (existing) existing.value = value
else global.headers.push({ key: 'Content-Security-Policy', value })
writeFileSync(file, JSON.stringify(config, null, 2) + '\n')
process.stdout.write(
  'Configured exact HTTPS/WSS CSP origins. Commit vercel.json before Vercel deployment.\n',
)
