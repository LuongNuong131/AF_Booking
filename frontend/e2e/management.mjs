// Exercises only disposable test accounts/data; all requests use the real API.
import { chromium, expect } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
const output = process.env.BOOKING_E2E_ARTIFACTS
if (!output || !process.env.BOOKING_E2E_PASSWORD) throw new Error('Set test credentials and artifact directory.')
await mkdir(output, { recursive: true })
const base = process.env.BOOKING_E2E_URL || 'http://localhost:5173', api = process.env.BOOKING_E2E_API || process.env.BOOKING_E2E_API_URL || 'http://localhost:8000/api/v1'
const number = String(Date.now()).slice(-7), key = `CW${number}-LAX-2611`, sibling = `CW${number}-LAX-2610`
async function send(url, token, body) {
  const r = await fetch(api + url, { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) })
  if (!r.ok) throw new Error(`${url}: ${r.status}`)
  return r.json()
}
const admin = await send('/auth/login', null, { username: 'admin', password: process.env.BOOKING_E2E_PASSWORD })
await send('/admin/bookings/import', admin.access_token, { data: `Booking Number,Suppliers,Station Code\n${key},Isolated Test Supplier,LAX\n${sibling},Isolated Test Supplier,LAX\n`, apply: true })
const agent = await send('/auth/login', null, { username: 'agent', password: process.env.BOOKING_E2E_PASSWORD })
const original = await send(`/bookings/lookup?key=${key}`, agent.access_token)
await send(`/bookings/${key}/notes`, agent.access_token, { status_code: 'BUNDLE', note: 'Local management browser test update', expected_version: original.version, client_request_id: crypto.randomUUID() })
const browser = await chromium.launch({ headless: true, ...(process.env.BOOKING_CHROMIUM_PATH ? { executablePath: process.env.BOOKING_CHROMIUM_PATH } : {}) })
const errors = [], metrics = []
async function navigate(page, target) { await page.evaluate(async target => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push(target) }, target) }
async function settle(page) { await expect(page.locator('.request-loading')).toHaveCount(0, { timeout: 20000 }); await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))) }
try {
 for (const role of ['agent', 'qc', 'admin']) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, reducedMotion: 'reduce', acceptDownloads: true })
  const page = await context.newPage()
  page.on('pageerror', e => errors.push(`${role}: ${e.message}`))
  await expect(async () => { await page.goto(`${base}/login`); await expect(page.getByLabel('Username', { exact: true })).toBeVisible() }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill(role)
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.locator('.topbar')).toBeVisible()
  // Every booking row has its own classification action.
  await navigate(page, '/summary')
  await page.locator('.summary-search input').fill(key)
  const row = page.locator('tr[data-nav-key]').filter({ hasText: `CW ${number}-LAX-2611` })
  await expect(row).toBeVisible()
  await row.locator('.classification-trigger').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Other monthly bookings keep their own classification')
  const type = role === 'qc' ? 'transportation' : 'hotel'
  if (await dialog.getByLabel('Type', { exact: true }).inputValue() === type) await dialog.getByLabel('Type', { exact: true }).selectOption(type === 'hotel' ? 'transportation' : 'hotel')
  else await dialog.getByLabel('Type', { exact: true }).selectOption(type)
  await dialog.getByRole('button', { name: 'Save classification', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  const token = await page.evaluate(() => localStorage.getItem('booking.access_token'))
  expect((await send(`/bookings/lookup?key=${sibling}`, token)).snapshot.supplier_type).toBe('unclassified')
  await navigate(page, `/summary/${key}`)
  await page.getByLabel('Note', { exact: true }).fill(`Keep unsaved note for ${role}`)
  await page.locator('.booking-summary-card .classification-trigger').click()
  const editor = page.getByRole('dialog')
  await editor.getByLabel('Type', { exact: true }).selectOption(await editor.getByLabel('Type', { exact: true }).inputValue() === 'hotel' ? 'transportation' : 'hotel')
  await editor.getByRole('button', { name: 'Save classification', exact: true }).click()
  await expect(editor).not.toBeVisible()
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue(`Keep unsaved note for ${role}`)
  // The report page and actual download share the same applied scope/filter values.
  await navigate(page, role === 'agent' ? '/reports' : '/reports?scope=team')
  await expect(page.locator('.report-kpis')).toBeVisible({ timeout: 20000 })
  if (role === 'agent') {
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Export Excel', exact: true }).click()
    await (await download).saveAs(path.join(output, 'agent-report.xlsx'))
  }
  await page.screenshot({ path: path.join(output, `${role}-report-desktop.png`), fullPage: true })
  const routes = ['/reports', '/reports/mine', `/summary/${key}`, '/summary', '/tickets']
  if (role === 'admin') routes.push('/admin/tickets', '/admin/data', '/admin/users', '/admin/bookings', '/admin/statuses', '/admin/trash', '/admin/system', '/admin/integrity')
  for (const width of [320, 375, 768, 1024, 1440]) {
   await page.setViewportSize({ width, height: 1000 })
   for (const route of routes) {
    await navigate(page, route)
    await expect(page.locator('#main-content h1').first()).toBeVisible()
    await settle(page)
    const metric = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }))
    metrics.push({ role, route, ...metric })
    if (metric.document > width + 1) {
      await page.screenshot({ path: path.join(output, 'overflow.png'), fullPage: true })
      throw new Error(`Overflow ${JSON.stringify(metrics.at(-1))}`)
    }
    if (width === 375 && ['/reports', '/admin/system', '/admin/data', '/admin/trash'].includes(route)) await page.screenshot({ path: path.join(output, `${role}-375-${route.replaceAll('/', '_')}.png`), fullPage: true })
   }
  }
  if (role === 'admin') {
   await page.setViewportSize({ width: 1440, height: 1100 })
   await navigate(page, '/admin/data?resource=users')
   await expect(page.locator('.data-console')).toBeVisible()
   await settle(page)
   await page.getByRole('button', { name: 'Create record', exact: true }).click()
   const form = page.getByRole('dialog')
   await page.setViewportSize({ width: 375, height: 1000 })
   await form.getByLabel('Username', { exact: true }).fill(`browser.${number}`)
   await form.getByLabel('Full name', { exact: true }).fill(`Browser temporary ${number}`)
   await form.getByLabel('Temporary password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
   await form.getByRole('button', { name: 'Save changes', exact: true }).click()
   await expect(form).not.toBeVisible()
   await page.setViewportSize({ width: 1440, height: 1100 })
   await navigate(page, '/admin/users')
   const userRow = page.locator('tbody tr').filter({ hasText: `browser.${number}` })
   await expect(userRow).toBeVisible()
   await userRow.getByRole('button', { name: 'Delete', exact: true }).click()
   let binDialog = page.getByRole('dialog')
   await binDialog.getByLabel('Reason for deletion', { exact: true }).fill('Delete browser-only test user')
   await binDialog.getByRole('button', { name: 'Move to recycle bin', exact: true }).click()
   await expect(binDialog).not.toBeVisible()
   await expect(userRow).toHaveCount(0)
   await navigate(page, '/admin/trash')
   const trashRow = page.locator('tbody tr').filter({ hasText: `Browser temporary ${number}` })
   await expect(trashRow).toBeVisible()
   await trashRow.getByRole('button', { name: 'Restore', exact: true }).click()
   await expect(trashRow).toHaveCount(0)
   await navigate(page, '/admin/users')
   await userRow.getByRole('button', { name: 'Delete', exact: true }).click()
   binDialog = page.getByRole('dialog')
   await binDialog.getByLabel('Reason for deletion', { exact: true }).fill('Purge isolated browser user')
   await binDialog.getByRole('button', { name: 'Move to recycle bin', exact: true }).click()
   await expect(binDialog).not.toBeVisible()
   await navigate(page, '/admin/trash')
   await page.getByRole('button', { name: 'Empty recycle bin', exact: true }).click()
   const purge = page.getByRole('dialog')
   await expect(purge.locator('.purge-counts')).toBeVisible()
   await expect(purge.getByRole('button', { name: 'Permanently delete reviewed data', exact: true })).toBeDisabled()
   await purge.getByLabel('Type DELETE to confirm permanent deletion', { exact: true }).fill('DELETE')
   await purge.getByRole('button', { name: 'Permanently delete reviewed data', exact: true }).click()
   await expect(purge).not.toBeVisible()
   await expect(trashRow).toHaveCount(0)
   await navigate(page, '/admin/system')
   await expect(page.locator('.system-kpis')).toBeVisible()
   await page.locator('.language-select select').selectOption('vi')
   await page.getByTitle('Giao diện', { exact: true }).click()
   await page.getByRole('menuitemradio', { name: 'Tối', exact: true }).click()
   await page.setViewportSize({ width: 375, height: 1000 })
   await page.screenshot({ path: path.join(output, 'system-375-dark-vi.png'), fullPage: true })
   await navigate(page, '/reports')
   await expect(page.locator('.report-kpis')).toBeVisible({ timeout: 20000 })
   await page.screenshot({ path: path.join(output, 'report-375-dark-vi.png'), fullPage: true })
  }
  await context.close()
 }
 expect(errors).toEqual([])
 await writeFile(path.join(output, 'management-browser-results.json'), JSON.stringify({ result: 'passed', metrics, errors }, null, 2))
 process.stdout.write(JSON.stringify({ result: 'passed', combinations: metrics.length, errors })+'\n')
} finally { await browser.close() }
