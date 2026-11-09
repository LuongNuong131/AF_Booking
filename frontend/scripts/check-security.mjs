import assert from 'node:assert/strict'
import { ESLint } from 'eslint'
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
const eslint = new ESLint()
const [probe] = await eslint.lintText('<template><div v-html="content" /></template>', {
  filePath: 'src/security-probe.vue',
})
assert(
  probe.messages.some(
    (message) => message.ruleId === 'vue/no-v-html' && message.severity === 2,
  ),
  'vue/no-v-html must reject unsafe rendering',
)
process.stdout.write('Unsafe HTML rendering is rejected by ESLint.\n')

function build(overrides) {
  return spawnSync(process.execPath, ['node_modules/vite/bin/vite.js', 'build'], {
    encoding: 'utf8',
    env: {
      ...process.env,
      VERCEL: '1',
      VITE_API_BASE_URL: '',
      VITE_WS_URL: '',
      VITE_SENTRY_DSN: '',
      ...overrides,
    },
  })
}
for (const [url, message] of [
  ['', 'VITE_API_URL is required for production'],
  ['http://insecure.example/api/v1', 'VITE_API_URL must use HTTPS in production'],
]) {
  const rejected = build({ VITE_API_URL: url })
  assert(
    rejected.status !== 0 && (rejected.stdout + rejected.stderr).includes(message),
    'Vercel must reject missing or insecure API configuration',
  )
}
process.stdout.write('Vercel rejects missing and insecure API configuration.\n')

const source = readFileSync('vercel.json', 'utf8')
const generated = build({
  VITE_API_URL: 'https://deployment-check.onrender.com/api/v1',
  VITE_SENTRY_DSN: 'https://public@errors.example.com/42',
})
assert.equal(generated.status, 0, generated.stdout + generated.stderr)
assert.equal(readFileSync('vercel.json', 'utf8'), source, 'Build must not mutate source config')
const config = JSON.parse(readFileSync('.vercel/output/config.json', 'utf8'))
assert.equal(config.version, 3)
const csp = config.routes[0].headers['Content-Security-Policy']
assert(
  csp.includes(
    "connect-src 'self' https://deployment-check.onrender.com wss://deployment-check.onrender.com https://errors.example.com;",
  ),
  'Generated CSP must allow the bundle API, derived WebSocket and configured Sentry origin',
)
assert(!csp.includes('api.example.com') && !csp.includes('*') && !csp.includes('unsafe-eval'))
for (const file of ['index.html', 'sw.js', 'manifest.webmanifest']) {
  assert.equal(
    readFileSync(`.vercel/output/static/${file}`, 'utf8'),
    readFileSync(`dist/${file}`, 'utf8'),
    `Vercel output must include the final ${file}`,
  )
}
const fallback = config.routes.at(-1)
assert.equal(fallback.dest, '/index.html')
const match = new RegExp(`^${fallback.src}$`)
assert(match.test('/login') && match.test('/bookings/CW123-SGN-2611'))
for (const path of ['/assets/missing.js', '/icons/missing.svg', '/sw.js', '/manifest.webmanifest']) {
  assert(!match.test(path), `Missing static file ${path} must not return HTML`)
}
const workerRoute = config.routes.find((route) => route.headers?.['Service-Worker-Allowed'])
assert.equal(workerRoute.headers['Cache-Control'], 'no-cache, max-age=0, must-revalidate')
process.stdout.write('Vercel output includes exact CSP origins, SPA routing, and final PWA files.\n')
