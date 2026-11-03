import { chromium, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
const artifacts = process.env.BOOKING_E2E_ARTIFACTS
await mkdir(artifacts, { recursive: true })
const browser = await chromium.launch({
  headless: true,
  ...(process.env.BOOKING_CHROMIUM_PATH
    ? { executablePath: process.env.BOOKING_CHROMIUM_PATH }
    : {}),
})
const context = await browser.newContext({
  viewport: { width: 1440, height: 1050 },
  reducedMotion: 'reduce',
})
const page = await context.newPage(),
  errors = []
page.on('pageerror', (e) => errors.push(e.name))
try {
  await expect(async () => {
    await page.goto('http://localhost:5173')
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill('agent')
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible()
  const KEY = 'CW2154654-RDU-2609'
  let lookupCount = 0
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/v1/bookings/lookup') lookupCount++
  })
  const input = page.getByLabel('Smart search', { exact: true })
  await input.fill('cw 2154654 - rdu - 2609')
  await expect(page.locator('.booking-summary-card')).toContainText('CW 2154654-RDU-2609')
  const afterPrefetch = lookupCount
  await input.press('Enter')
  expect(lookupCount).toBe(afterPrefetch)
  await page.route('**/api/v1/bookings/*/notes', async (route) => {
    if (route.request().method() === 'POST')
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ code: 'SERVICE_BUSY', message: 'Test server waking' }),
      })
    else await route.continue()
  })
  await context.setOffline(true)
  for (const text of ['First offline update', 'Second offline update']) {
    await page
      .getByRole('button', { name: /^Bundle/ })
      .first()
      .click()
    await page.getByLabel('Note', { exact: true }).fill(text)
    await page.getByRole('button', { name: /^Save update/ }).click()
    await expect(page.getByLabel('Note', { exact: true })).toHaveValue('')
    await expect(page.locator('.timeline-item').filter({ hasText: text })).toContainText('Unsent')
    await expect(input).toBeFocused()
  }
  await expect(page.locator('.outbox-panel summary')).toContainText('2 unsent')
  await expect(page.locator('.mine-booking').first()).toContainText('Second offline update')
  await context.setOffline(false)
  await page.reload()
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible()
  await expect(page.locator('.outbox-panel summary')).toContainText('2 unsent')
  await input.fill(KEY)
  await input.press('Enter')
  await expect(page.locator('.outgoing-note')).toHaveCount(2)
  await page.screenshot({ path: path.join(artifacts, 'outbox-pending.png'), fullPage: true })
  const payloads = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/notes'))
      payloads.push(request.postDataJSON())
  })
  await page.unroute('**/api/v1/bookings/*/notes')
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect(page.locator('.outbox-panel')).toHaveCount(0, { timeout: 20000 })
  await expect(page.locator('.outgoing-note')).toHaveCount(0)
  await expect(page.locator('.timeline-item')).toHaveCount(3)
  expect(payloads).toHaveLength(2)
  expect(payloads[0].expected_version).toBe(1)
  expect(payloads[1].expected_version).toBe(2)
  expect(payloads[0].client_request_id).not.toBe(payloads[1].client_request_id)
  await page.reload()
  await input.fill(KEY)
  await input.press('Enter')
  await expect(page.locator('.timeline-item')).toHaveCount(3)
  expect(errors).toEqual([])
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally {
  await context.close()
  await browser.close()
}
