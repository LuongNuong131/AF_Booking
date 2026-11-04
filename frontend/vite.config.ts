import { readFileSync } from 'node:fs'
import { buildCsp } from './src/config/csp'
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { staticPwa } from './pwa-build'
import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import { resolveEndpoints } from './src/config/api-url'

export default defineConfig(({ command, mode }) => {
  const publicEnv = loadEnv(mode, process.cwd(), 'VITE_')
  const apiOrigin = new URL(
    resolveEndpoints({ ...publicEnv, ...process.env }, command === 'build').apiUrl,
  ).origin
  const endpoints = resolveEndpoints({ ...publicEnv, ...process.env }, command === 'build')
  const csp = endpoints.apiUrl.startsWith('https:')
    ? buildCsp(endpoints.apiUrl, endpoints.wsUrl)
    : null
  if (command === 'build' && process.env.VERCEL === '1') {
    const config = JSON.parse(readFileSync(new URL('./vercel.json', import.meta.url), 'utf8'))
    const saved = config.headers
      .flatMap((row: { headers: Array<{ key: string; value: string }> }) => row.headers)
      .find((h: { key: string }) => h.key.toLowerCase() === 'content-security-policy')?.value
    if (saved !== csp)
      throw new Error(
        'Configure and commit exact CSP origins with npm run configure:csp before deploying Vercel.',
      )
  }
  if (command === 'build') {
    const env = loadEnv(mode, process.cwd(), 'VITE_')
    resolveEndpoints({ ...env, ...process.env }, true)
  }
  return {
    plugins: [
      vue(),
      staticPwa(),
      {
        name: 'api-preconnect',
        transformIndexHtml: () => [
          {
            tag: 'link',
            attrs: { rel: 'preconnect', href: apiOrigin, crossorigin: '' },
            injectTo: 'head',
          },
          {
            tag: 'link',
            attrs: { rel: 'dns-prefetch', href: apiOrigin },
            injectTo: 'head',
          },
        ],
      },
    ],
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    preview: { headers: csp ? { 'Content-Security-Policy': csp } : {} },
    server: { port: 5173, strictPort: true },
    test: {
      environment: 'happy-dom',
      clearMocks: true,
      server: { deps: { inline: ['element-plus'] } },
    },
  }
})
