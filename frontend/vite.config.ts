import { buildCsp } from './src/config/csp'
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { staticPwa } from './pwa-build'
import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import { resolveEndpoints } from './src/config/api-url'
import { vercelOutput } from './vercel-build'

export default defineConfig(({ command, mode }) => {
  const publicEnv = loadEnv(mode, process.cwd(), 'VITE_')
  const endpoints = resolveEndpoints({ ...publicEnv, ...process.env }, command === 'build')
  const apiOrigin = new URL(endpoints.apiUrl).origin
  const csp = endpoints.apiUrl.startsWith('https:')
    ? buildCsp(
        endpoints.apiUrl,
        endpoints.wsUrl,
        process.env.VITE_SENTRY_DSN ?? publicEnv.VITE_SENTRY_DSN,
      )
    : null
  return {
    plugins: [
      vue(),
      staticPwa(),
      vercelOutput(csp),
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
