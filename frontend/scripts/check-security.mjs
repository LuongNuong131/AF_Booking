import assert from 'node:assert/strict'
import { ESLint } from 'eslint'
import { spawnSync } from 'node:child_process'
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

const mismatched = spawnSync(process.execPath, ['node_modules/vite/bin/vite.js', 'build'], {
  encoding: 'utf8',
  env: {
    ...process.env,
    VERCEL: '1',
    VITE_API_URL: 'https://csp-mismatch.invalid/api/v1',
    VITE_WS_URL: '',
  },
})
assert(
  mismatched.status !== 0 &&
    (mismatched.stdout + mismatched.stderr).includes('Configure and commit exact CSP origins'),
  'Vercel must reject an unconfigured API origin',
)
process.stdout.write('Vercel build rejects a mismatched CSP origin.\n')
