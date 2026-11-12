import { chromium, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
const output = process.env.BOOKING_E2E_ARTIFACTS, api = process.env.BOOKING_E2E_API_URL
if (!output || !api || !process.env.BOOKING_E2E_PASSWORD) throw new Error('Disposable browser fixtures required')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: process.env.BOOKING_CHROMIUM_PATH || '/usr/bin/chromium' })
const errors = [], KEY = 'CW2154654-RDU-2609', FOLDER = 'CW2154654-RDU', FUTURE = 'CW2154654-RDU-2610'
async function login(username) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 }, reducedMotion: 'reduce' })
  const page = await context.newPage()
  page.on('pageerror', e => errors.push(e.message))
  await expect(async () => { await page.goto('http://localhost:5173/login'); await expect(page.getByLabel('Username', { exact: true })).toBeVisible() }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.locator('.topbar')).toBeVisible()
  return page
}
async function navigate(page, target) {
  await page.evaluate(async target => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push(target) }, target)
}
async function apiRequest(page, route, method = 'GET', body) {
  const token = await page.evaluate(() => localStorage.getItem('booking.access_token'))
  const r = await fetch(api + route, { method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) })
  if (!r.ok) throw new Error(`${route}: ${r.status} ${await r.text()}`)
  return r.json()
}
try {
  const admin = await login('admin')
  await navigate(admin, `/summary/folders/${FOLDER}`)
  await admin.getByRole('button', { name: 'Follow folder', exact: true }).click()
  await expect(admin.getByRole('button', { name: 'Unfollow folder', exact: true })).toBeVisible()
  await admin.reload()
  try { await expect(admin.getByRole('button', { name: 'Unfollow folder', exact: true })).toBeVisible({ timeout: 15000 }) }
  catch (error) { await admin.screenshot({ path: path.join(output, 'reload-failure.png'), fullPage: true }); console.warn(await admin.locator('body').innerText()); console.warn(JSON.stringify({ api: await apiRequest(admin, `/folders/${FOLDER}/follow`), store: await admin.evaluate(() => { const p = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia; return { following: p._s.get('collaboration').followingFolders, pending: p._s.get('collaboration').folderPending, epoch: p._s.get('auth').epoch } }) })); throw error }
  await navigate(admin, '/')
  const input = admin.getByLabel('Smart search', { exact: true })
  await input.fill(KEY); await input.press('Enter')
  await expect(admin.locator('.booking-summary-card')).toContainText('CW 2154654-RDU-2609')
  await admin.getByRole('button', { name: 'Follow booking', exact: true }).first().click()
  await expect(admin.getByRole('button', { name: 'Unfollow booking', exact: true }).first()).toBeVisible()
  await admin.getByRole('button', { name: 'Following', exact: true }).click()
  await expect(admin.locator('.followed-folder')).toHaveCount(1)
  const other = await login('other')
  expect((await apiRequest(other, `/folders/${FOLDER}/follow`)).following).toBe(false)
  await apiRequest(other, `/bookings/${FUTURE}/notes`, 'POST', {
    status_code: 'BUNDLE', note: 'A new monthly booking in a followed folder', expected_version: 0,
    client_request_id: crypto.randomUUID(), confirm_new: true, supplier_name: 'Example Hotel', supplier_type: 'hotel',
  })
  await expect(async () => {
    const notices = (await apiRequest(admin, '/notifications')).items.filter(n => n.booking_key === FUTURE)
    expect(notices).toHaveLength(1); expect(notices[0].merged_count).toBe(1)
  }).toPass({ timeout: 10000 })
  await admin.locator('.followed-folder .folder-card').click()
  await expect(admin.locator('.month-row')).toHaveCount(2)
  await admin.locator('.month-row').filter({ hasText: '2610' }).click()
  await expect(admin.locator('.booking-summary-card')).toContainText('CW 2154654-RDU-2610')
  await expect(admin.getByRole('button', { name: 'Follow booking', exact: true }).first()).toBeVisible()
  await expect(admin.getByRole('button', { name: 'Unfollow folder', exact: true }).first()).toBeVisible()
  await navigate(admin, '/')
  await admin.getByRole('button', { name: 'Following', exact: true }).click()
  await expect(admin.locator('.followed-folder')).toHaveCount(1)
  for (const width of [320, 375, 768, 1440]) {
    await admin.setViewportSize({ width, height: 1000 })
    await admin.evaluate(() => scrollTo(0, 0))
    expect(await admin.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await admin.screenshot({ path: path.join(output, `folder-follow-${width}.png`), fullPage: true })
  }
  await admin.locator('.followed-folder').getByRole('button', { name: 'Unfollow folder', exact: true }).click()
  await expect(admin.locator('.followed-folder')).toHaveCount(0)
  await admin.locator('.follow-view-tabs').getByRole('button', { name: 'Bookings', exact: true }).click()
  await expect(admin.locator('.collaboration-list tbody')).toContainText('CW 2154654-RDU-2609')
  expect((await apiRequest(admin, `/folders/${FOLDER}/follow`)).following).toBe(false)
  expect((await apiRequest(admin, '/watching')).total).toBe(1)
  expect(errors).toEqual([])
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally { await browser.close() }
