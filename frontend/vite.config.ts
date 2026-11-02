import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import { resolveApiBaseUrl } from './src/config/api-url'

export default defineConfig(({ command, mode }) => {
  if (command === 'build') {
    const env = loadEnv(mode, process.cwd(), 'VITE_')
    resolveApiBaseUrl(process.env.VITE_API_BASE_URL ?? env.VITE_API_BASE_URL, true)
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
