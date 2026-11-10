// Real local API/MySQL browser verification; no API interception or production data.
import { chromium, expect } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
const output = process.env.BOOKING_E2E_ARTIFACTS
if (!output || !process.env.BOOKING_E2E_PASSWORD) throw new Error('Configure the test account and artifacts directory.')
await mkdir(output, { recursive: true })
const base = process.env.BOOKING_E2E_URL || 'http://localhost:5173'
const api = process.env.BOOKING_E2E_API || 'http://localhost:8000/api/v1'
const KEY = 'CW2154654-RDU-2609'
async function send(route, token, body) {
  const response = await fetch(`${api}${route}`, {
    method: body ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  if (!response.ok) throw new Error(`${route}: ${response.status}`)
  return response.json()
}
const auth = await send('/auth/login', null, { username: 'agent', password: process.env.BOOKING_E2E_PASSWORD })
for (const key of [KEY, 'CW2154654-RDU-2610', 'CW2154655-YUL-2610']) {
  let booking = await send(`/bookings/lookup?key=${key}`, auth.access_token)
  if (!booking.exists) {
    await send('/bookings', auth.access_token, { booking_key: key, supplier_name: key.includes('RDU') ? 'Airport Hotel RDU' : 'Crew Shuttle YUL', supplier_type: key.includes('RDU') ? 'hotel' : 'transportation', confirm_new: true })
    booking = await send(`/bookings/lookup?key=${key}`, auth.access_token)
  }
  if (!booking.history.items.length) await send(`/bookings/${key}/notes`, auth.access_token, { status_code: 'BUNDLE', note: 'Supplier follow-up in progress', expected_version: booking.version, client_request_id: crypto.randomUUID() })
}
const tasks = await send(`/work-tasks?booking_key=${KEY}&status=all`, auth.access_token)
if (!tasks.items.length) await send(`/bookings/${KEY}/work-tasks`, auth.access_token, { message: 'Please review the supplier invoice and confirm the booking details.', client_request_id: crypto.randomUUID() })
const browser = await chromium.launch({ headless: true, executablePath: process.env.BOOKING_CHROMIUM_PATH || '/usr/bin/chromium' })
const errors = [], metrics = []
try {
  for (const role of (process.env.BOOKING_E2E_ROLES || 'agent,qc,admin').split(',')) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' })
    const page = await context.newPage()
    page.on('pageerror', e => errors.push(e.message))
    await page.goto(`${base}/login`)
    await page.getByLabel('Username', { exact: true }).fill(role)
    await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.locator('.topbar')).toBeVisible()
    await page.getByLabel('Smart search', { exact: true }).fill(KEY)
    await page.getByLabel('Smart search', { exact: true }).press('Enter')
    await expect(page.locator('.booking-summary-card .classification-trigger')).toBeVisible()
    const draft = `Keep this unsaved draft for ${role}`
    await page.getByLabel('Note', { exact: true }).fill(draft)
    const before = await send(`/bookings/lookup?key=${KEY}`, await page.evaluate(() => localStorage.getItem('booking.access_token')))
    const previous = await page.locator('.booking-summary-card .summary-metadata').innerText()
    const nextType = previous.includes('Transportation') ? 'hotel' : 'transportation'
    await page.locator('.booking-summary-card .classification-trigger').click()
    const form = page.locator('.booking-summary-card .supplier-edit-form')
    await expect(form).toContainText('all monthly bookings')
    await form.getByLabel('Type', { exact: true }).selectOption(nextType)
    const saving = page.waitForResponse(r => r.url().endsWith('/folders/CW2154654-RDU') && r.request().method() === 'PATCH')
    await form.getByRole('button', { name: 'Save classification', exact: true }).click()
    const response = await saving
    expect(response.status()).toBe(200)
    expect(response.request().postDataJSON()).toEqual({ supplier_type: nextType })
    await expect(page.locator('.supplier-save-success')).toContainText('classification updated')
    await expect(page.locator('.booking-summary-card .summary-metadata')).toContainText(nextType === 'hotel' ? 'Hotel' : 'Transportation')
    await expect(page.getByLabel('Note', { exact: true })).toHaveValue(draft)
    const after = await send(`/bookings/lookup?key=${KEY}`, await page.evaluate(() => localStorage.getItem('booking.access_token')))
    expect(after.history).toEqual(before.history)
    for (const field of ['version', 'updated_at', 'last_agent', 'last_status']) expect(after.snapshot[field]).toEqual(before.snapshot[field])
    await page.screenshot({ path: path.join(output, `${role}-workspace.png`), fullPage: true })
    // All feature surfaces, including populated reports, tables and tickets.
    const routes = ['/', '/summary', '/summary?view=folders', `/summary/${KEY}`, '/summary/folders/CW2154654-RDU', '/search/notes?q=Supplier', '/profile', '/reports/mine', '/tickets']
    if (role !== 'agent') routes.push('/reports', '/reports/daily')
    if (role === 'admin') routes.push('/admin/users', '/admin/bookings', '/admin/import', '/admin/suppliers', '/admin/statuses', '/admin/audit', '/admin/trash', '/admin/integrity', '/admin/system')
    for (const width of [320, 375, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 1000 })
      for (const route of routes) {
        await page.evaluate(async route => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push(route) }, route)
        await expect(page.locator('#main-content h1').first()).toBeVisible()
        await expect(page.locator('.request-loading')).toHaveCount(0, { timeout: 15000 })
        await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))
        const metric = await page.evaluate(() => ({ width: innerWidth, content: document.documentElement.scrollWidth }))
        metrics.push({ role, route, ...metric })
        expect(metric.content, `${role} ${route} at ${width}`).toBeLessThanOrEqual(width + 1)
        if (width === 375 && ['/tickets', '/reports/mine', '/reports/daily'].includes(route)) {
          if (route.includes('reports') && await page.locator('.booking-table').count()) await expect(page.locator('.booking-table thead').first()).toBeVisible()
          await page.screenshot({ path: path.join(output, `${role}-375-${route.replaceAll('/', '_')}.png`), fullPage: true })
        }
      }
    }
    await page.evaluate(async () => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push('/summary/CW2154654-RDU-2609') })
    await expect(page.locator('.classification-trigger')).toBeVisible()
    await page.setViewportSize({ width: 375, height: 900 })
    await page.locator('.language-select select').first().selectOption('vi')
    await page.getByTitle('Giao diện', { exact: true }).click()
    await page.getByRole('menuitemradio', { name: 'Tối', exact: true }).click()
    await page.getByRole('button', { name: 'Sửa phân loại', exact: true }).click()
    await expect(page.locator('.supplier-edit-form')).toContainText('tất cả booking tháng')
    await page.screenshot({ path: path.join(output, `${role}-375-classification-dark-vi.png`), fullPage: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(376)
    await context.close()
  }
  expect(errors).toEqual([])
  await writeFile(path.join(output, 'classification-metrics.json'), JSON.stringify({ result: 'passed', metrics, errors }, null, 2))
  process.stdout.write(JSON.stringify({ result: 'passed', routesChecked: metrics.length, errors }) + '\n')
} finally { await browser.close() }
