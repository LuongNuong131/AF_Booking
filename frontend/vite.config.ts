import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import { resolveEndpoints } from './src/config/api-url'

export default defineConfig(({ command, mode }) => {
  if (command === 'build') {
    const env = loadEnv(mode, process.cwd(), 'VITE_')
    resolveEndpoints({ ...env, ...process.env }, true)
  }
  return {
    plugins: [vue()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: { port: 5173, strictPort: true },
    test: {
      environment: 'happy-dom',
      clearMocks: true,
      server: { deps: { inline: ['element-plus'] } },
    },
  }
})
