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
    server: { port: 5173, strictPort: true },
    test: {
      environment: 'happy-dom',
      clearMocks: true,
      server: { deps: { inline: ['element-plus'] } },
    },
  }
})
