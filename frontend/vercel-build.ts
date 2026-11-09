import { cpSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { Plugin, ResolvedConfig } from 'vite'

// Build Output API routes are generated alongside the bundle, so the browser's
// CSP always uses the same validated API/WS/Sentry origins as that bundle.
export function vercelConfig(csp: string) {
  return {
    version: 3,
    routes: [
      {
        src: '/(.*)',
        headers: {
          'X-Content-Type-Options': 'nosniff',
          'Referrer-Policy': 'strict-origin-when-cross-origin',
          'X-Frame-Options': 'DENY',
          'Content-Security-Policy': csp,
        },
        continue: true,
      },
      {
        src: '/assets/(.*)',
        headers: { 'Cache-Control': 'public, max-age=31536000, immutable' },
        continue: true,
      },
      {
        src: '/sw\\.js$',
        headers: {
          'Cache-Control': 'no-cache, max-age=0, must-revalidate',
          'Service-Worker-Allowed': '/',
        },
        continue: true,
      },
      {
        src: '/manifest\\.webmanifest$',
        headers: { 'Cache-Control': 'no-cache' },
        continue: true,
      },
      { handle: 'filesystem' },
      {
        src: '/((?!assets/|icons/|sw\\.js$|manifest\\.webmanifest$).*)',
        dest: '/index.html',
      },
    ],
  }
}

export function vercelOutput(csp: string | null): Plugin {
  let config: ResolvedConfig
  let failed = false
  return {
    name: 'vercel-build-output',
    apply: 'build',
    configResolved(resolved) {
      config = resolved
    },
    buildEnd(error) {
      failed = Boolean(error)
    },
    renderError() {
      failed = true
    },
    closeBundle: {
      // staticPwa creates sw.js in closeBundle; copy only after it finishes.
      order: 'post',
      handler() {
        if (failed) return
        if (!csp) throw new Error('Vercel output requires a production CSP.')
        const output = resolve(config.root, '.vercel/output')
        rmSync(output, { recursive: true, force: true })
        mkdirSync(output, { recursive: true })
        cpSync(resolve(config.root, config.build.outDir), resolve(output, 'static'), {
          recursive: true,
        })
        writeFileSync(
          resolve(output, 'config.json'),
          JSON.stringify(vercelConfig(csp), null, 2) + '\n',
        )
      },
    },
  }
}
