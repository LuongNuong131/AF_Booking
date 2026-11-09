import { chromium, expect } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
const output = process.env.BOOKING_E2E_ARTIFACTS
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.env.BOOKING_CHROMIUM_PATH ? { executablePath: process.env.BOOKING_CHROMIUM_PATH } : {}) })
const errors = [], metrics = []
const routes = ['/', '/summary', '/summary?view=folders', '/summary/CW2154654-RDU-2609', '/profile', '/reports', '/admin/users', '/admin/bookings', '/admin/import', '/admin/suppliers', '/admin/statuses', '/admin/audit', '/admin/system']
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' })
  const page = await context.newPage()
  const pending = new Set()
  page.on('request', request => pending.add(request))
  page.on('requestfinished', request => pending.delete(request))
  page.on('requestfailed', request => pending.delete(request))
  page.on('pageerror', e => errors.push(e.message))
  await expect(async () => { await page.goto('http://localhost:5173/login'); await expect(page.locator('input[type="password"]')).toBeVisible() }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill('admin')
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.locator('.topbar')).toBeVisible()
  for (const width of [320, 375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    for (const route of routes) {
      // Use SPA navigation, as the UI does, instead of 65 full sign-in bootstrap
      // requests that can trip the authentication endpoint's per-minute limit.
      await page.evaluate(async target => {
        await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push(target)
      }, route)
      await expect(page.locator('#main-content h1').first()).toBeVisible().catch(async error => {
        await page.screenshot({ path: path.join(output, 'route-failed.png'), fullPage: true })
        throw new Error(JSON.stringify({ route, width, url: page.url(), errors, body: await page.locator('body').innerText() }) + '\n' + error.message)
      })
      const painted = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      await painted()
      await expect.poll(() => pending.size, { timeout: 15000 }).toBe(0)
      await painted()
      const metric = await page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth, title: document.querySelector('h1')?.textContent,
        overflow: [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > innerWidth + 1 && el.getBoundingClientRect().width > 0).slice(0, 12).map(el => ({tag:el.tagName, class:el.className, right:el.getBoundingClientRect().right})) }))
      metrics.push({ route, ...metric })
      if (!process.env.BOOKING_RESPONSIVE_BASELINE && metric.width > width + 1) {
        await page.screenshot({ path: path.join(output, 'overflow.png'), fullPage: true })
        throw new Error(JSON.stringify({route,...metric}))
      }
      if ([375, 1440].includes(width) && ['/', '/summary', '/admin/import', '/admin/users', '/profile'].includes(route))
        await page.screenshot({ path: path.join(output, `${width}-${route.replaceAll('/', '_').replaceAll('?', '_') || 'home'}.png`), fullPage: true })
    }
  }
  await page.setViewportSize({ width: 375, height: 844 })
  await page.goto('http://localhost:5173/admin/users')
  await page.getByRole('button', { name: 'Create user', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  const bounds = await dialog.boundingBox()
  if (!process.env.BOOKING_RESPONSIVE_BASELINE) expect(bounds.x + bounds.width).toBeLessThanOrEqual(375)
  await page.screenshot({ path: path.join(output, '375-dialog.png'), fullPage: true })
  await page.keyboard.press('Escape')
  await page.locator('.language-select select').first().selectOption('vi')
  await expect(page.locator('html')).toHaveAttribute('lang', 'vi')
  await page.goto('http://localhost:5173/admin/import')
  await expect(page.getByRole('heading', { name: 'Nhập booking chưa có trạng thái' })).toBeVisible()
  await page.screenshot({ path: path.join(output, '375-import-vi.png'), fullPage: true })
  await page.getByTitle('Giao diện', { exact: true }).click()
  await page.getByRole('menuitemradio', { name: 'Tối', exact: true }).click()
  await page.screenshot({ path: path.join(output, '375-import-dark-vi.png'), fullPage: true })
  if (process.env.BOOKING_IMPORT_CSV_PATH) {
    await page.locator('.language-select select').first().selectOption('en')
    await page.locator('input[type="file"]').setInputFiles(process.env.BOOKING_IMPORT_CSV_PATH)
    await page.locator('.import-options select').selectOption('station_code')
    await page.locator('.import-options input[type="checkbox"]').check()
    await page.getByRole('button', { name: 'Preview import', exact: true }).click()
    await expect(page.locator('.import-preview')).toContainText('1400', { timeout: 65000 })
    await expect(page.locator('.import-preview')).toContainText('1425')
    await page.locator('.import-changes summary').click()
    await expect(page.locator('.import-changes tbody tr')).toHaveCount(14)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(376)
    await page.screenshot({ path: path.join(output, '375-full-csv-preview.png'), fullPage: true })
    // Preview only: the real import/idempotency checks run in the database suite.
  }
  if (!process.env.BOOKING_RESPONSIVE_BASELINE) {
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(376)
    expect(errors).toEqual([])
  }
  await writeFile(path.join(output, 'responsive-metrics.json'), JSON.stringify({ metrics, errors }, null, 2))
  await context.close()
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally { await browser.close() }
