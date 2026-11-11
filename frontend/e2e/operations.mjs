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
  errors = []
async function login(username) {
  const ctx = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
      reducedMotion: 'reduce',
    }),
    page = await ctx.newPage()
  page.on('pageerror', (e) => errors.push(e.message))
  await page.addInitScript(() => {
    window.__permissionRequests = 0
    if (typeof Notification !== 'undefined') {
      const original = Notification.requestPermission.bind(Notification)
      Notification.requestPermission = (...args) => {
        window.__permissionRequests++
        return original(...args)
      }
    }
  })
  await expect(async () => {
    await page.goto('http://localhost:5173')
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible({
    timeout: 15000,
  })
  return { ctx, page }
}
try {
  const admin = await login('admin'),
    agent = await login('agent'),
    qc = await login('qc')
  await agent.page.keyboard.press('Control+k')
  const palette = agent.page.getByRole('dialog', { name: 'Command palette', exact: true })
  await palette.getByRole('combobox').fill('Search notes')
  await palette.getByRole('combobox').press('Enter')
  await expect(agent.page).toHaveURL('http://localhost:5173/search/notes')
  await agent.page.getByLabel('Keyword', { exact: true }).fill('khách sạn')
  await agent.page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(agent.page.locator('.note-search-hit')).toHaveCount(1)
  await expect(agent.page.locator('.note-search-hit')).toContainText('2 matching note(s)')
  await expect(agent.page.locator('.note-search-hit mark')).toContainText('Khách sạn')
  await expect(agent.page.locator('.note-search-hit img')).toHaveCount(0)
  await expect(agent.page.locator('.note-search-hit')).toContainText('<img')
  await expect(agent.page).toHaveURL(/q=kh/)
  await expect(agent.page.locator('.note-search-result-count')).toContainText('1')
  await agent.page.screenshot({ path: path.join(artifacts, 'note-search-desktop.png'), fullPage: true })
  await agent.page.getByLabel('Keyword', { exact: true }).fill('contract')
  await expect(agent.page.locator('.note-search-draft-hint')).toBeVisible()
  await expect(agent.page.locator('.note-search-hit mark')).toContainText('Khách sạn')
  await agent.page.reload()
  await expect(agent.page.getByLabel('Keyword', { exact: true })).toHaveValue('khách sạn')
  await expect(agent.page.locator('.note-search-hit')).toHaveCount(1)
  await agent.page.locator('#notes-date-from').fill('2026-01-02')
  await agent.page.locator('#notes-date-to').fill('2026-01-01')
  await expect(agent.page.locator('.note-search-panel .field-error')).toBeVisible()
  await expect(agent.page.getByRole('button', { name: 'Search', exact: true })).toBeDisabled()
  await agent.page.getByRole('button', { name: 'Reset filters', exact: true }).click()
  await expect(agent.page.locator('#notes-date-from')).toHaveValue('')
  await expect(agent.page.getByRole('button', { name: 'Search', exact: true })).toBeEnabled()
  for (const width of [375, 320]) {
    await agent.page.setViewportSize({ width, height: 844 })
    await expect.poll(() => agent.page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1)
  }
  await agent.page.evaluate(() => document.documentElement.dataset.theme = 'dark')
  await agent.page.screenshot({ path: path.join(artifacts, 'note-search-mobile-dark.png'), fullPage: true })
  await agent.page.evaluate(() => delete document.documentElement.dataset.theme)
  await agent.page.setViewportSize({ width: 1440, height: 1000 })
  await command('system_sample')
  await expect(admin.page.locator('.nav-item .admin-degraded-dot')).toHaveCount(1)
  await admin.page.goto('http://localhost:5173/admin/system')
  await expect(
    admin.page.getByRole('heading', { name: 'System health', exact: true }),
  ).toBeVisible()
  await expect(admin.page.locator('.system-console')).toContainText('Slow queries')
  await expect(admin.page.locator('.system-console')).toContainText('reports.daily')
  await expect(admin.page.locator('.system-console')).not.toContainText('hidden-health-param')
  await expect(admin.page.locator('.system-console .report-trend polyline')).toHaveAttribute('points', /.+/)
  let healthReads = 0
  admin.page.on('request', (r) => {
    if (new URL(r.url()).pathname === '/api/v1/admin/system/detail') healthReads++
  })
  await admin.page.goto('http://localhost:5173/profile')
  await expect(admin.page.getByRole('heading', { name: 'Profile', exact: true })).toBeVisible()
  const before = healthReads
  await admin.page.waitForTimeout(15500)
  expect(healthReads).toBe(before)
  await expect(
    admin.page.getByRole('button', { name: 'Enable background push', exact: true }),
  ).toBeDisabled()
  expect(await admin.page.evaluate(() => window.__permissionRequests)).toBe(0)
  await qc.page.goto('http://localhost:5173/reports/daily')
  await expect(qc.page.locator('.daily-report-view .report-metrics article').first()).toContainText(
    '3',
  )
  await expect(qc.page.locator('.daily-report-view')).toContainText('RDU')
  const download = qc.page.waitForEvent('download')
  await qc.page.getByRole('button', { name: 'Download Excel', exact: true }).click()
  const file = await download
  expect(file.suggestedFilename()).toMatch(/^daily-report-\d{4}-\d{2}-\d{2}\.xlsx$/)
  await file.saveAs(path.join(artifacts, 'daily-report.xlsx'))
  await qc.page.emulateMedia({ media: 'print' })
  await expect(qc.page.locator('.daily-report-controls')).toBeHidden()
  await qc.page.emulateMedia({ media: 'screen' })
  await qc.page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => qc.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true)
  await qc.page.screenshot({
    path: path.join(artifacts, 'daily-report-mobile.png'),
    fullPage: true,
  })
  await agent.page.goto('http://localhost:5173/admin/system')
  await expect(agent.page).toHaveURL('http://localhost:5173/')
  expect(errors).toEqual([])
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally {
  input.close()
  await browser.close()
}
