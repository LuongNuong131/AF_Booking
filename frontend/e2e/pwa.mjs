import { chromium, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { createInterface } from 'node:readline'
import path from 'node:path'
const artifacts = process.env.BOOKING_E2E_ARTIFACTS
await mkdir(artifacts, { recursive: true })
const input = createInterface({ input: process.stdin })
let ack
input.on('line', (line) => {
  if (JSON.parse(line).ok) {
    ack?.()
    ack = null
  }
})
async function command(action) {
  const promise = new Promise((resolve) => (ack = resolve))
  process.stdout.write(JSON.stringify({ action }) + '\n')
  await promise
}
const browser = await chromium.launch({
    headless: true,
    ...(process.env.BOOKING_CHROMIUM_PATH
      ? { executablePath: process.env.BOOKING_CHROMIUM_PATH }
      : {}),
  }),
  context = await browser.newContext({ viewport: { width: 1280, height: 900 } }),
  page = await context.newPage(),
  errors = []
page.on('pageerror', (e) => errors.push(e.message))
await context.route('https://api.pwa.test/**', (route) =>
  route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ status: 'ok', database: 'connected' }),
    headers: { 'Access-Control-Allow-Origin': 'http://localhost:5173' },
  }),
)
async function cached() {
  return page.evaluate(async () => {
    const urls = []
    for (const key of await caches.keys())
      for (const request of await (await caches.open(key)).keys()) urls.push(request.url)
    return urls
  })
}
try {
  await expect(async () => {
    await page.goto('http://localhost:5173/login')
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  }).toPass({ timeout: 15000 })
  expect(await page.locator('script:not([src])').count()).toBe(0)
  const response = await page.request.get('http://localhost:5173/login')
  const csp = response.headers()['content-security-policy']
  expect(csp).toContain("connect-src 'self' https://api.pwa.test wss://api.pwa.test")
  expect(csp).toContain("script-src 'self';")
  expect(csp).toContain("frame-ancestors 'none'")
  await page.evaluate(() => {
    const script = document.createElement('script')
    script.textContent = 'window.inlineScriptExecuted=true'
    document.body.append(script)
  })
  expect(await page.evaluate(() => window.inlineScriptExecuted)).toBeUndefined()
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready
  })
  await page.reload()
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true)
  const manifest = await page.evaluate(
    async () => await (await fetch('/manifest.webmanifest')).json(),
  )
  expect(manifest.display).toBe('standalone')
  expect(manifest.icons).toHaveLength(2)
  await page.evaluate(
    async () => await fetch('https://api.pwa.test/api/v1/health/warm').then((r) => r.json()),
  )
  const urls = await cached()
  expect(urls.length).toBeGreaterThan(10)
  expect(
    urls.every((raw) => {
      const url = new URL(raw)
      return (
        url.origin === 'http://localhost:5173' &&
        !url.pathname.startsWith('/api/') &&
        (url.pathname.startsWith('/assets/') ||
          url.pathname.startsWith('/icons/') ||
          ['/index.html', '/manifest.webmanifest'].includes(url.pathname))
      )
    }),
  ).toBe(true)
  await context.setOffline(true)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  expect(await cached()).toEqual(urls)
  await context.setOffline(false)
  await command('pwa_update')
  await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.getRegistration()
    await registration.update()
  })
  await expect(page.locator('.pwa-update-banner')).toContainText(
    'A new version is available. Reload',
  )
  const navigation = page.waitForNavigation()
  await page.locator('.pwa-update-banner button').click()
  await navigation
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  await expect(page.locator('.pwa-update-banner')).toHaveCount(0)
  expect((await cached()).every((url) => !url.includes('/api/'))).toBe(true)
  await page.screenshot({ path: path.join(artifacts, 'pwa-offline-shell.png'), fullPage: true })
  expect(errors).toEqual([])
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally {
  input.close()
  await browser.close()
}
