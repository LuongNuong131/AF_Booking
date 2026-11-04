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
const KEY = 'CW2154654-RDU-2609',
  errors = []
async function login(username) {
  const ctx = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
      reducedMotion: 'reduce',
    }),
    page = await ctx.newPage()
  page.on('pageerror', (e) => errors.push(e.message))
  await expect(async () => {
    await page.goto('http://localhost:5173')
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  const signed = page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname.endsWith('/auth/login'),
  )
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  expect((await signed).status()).toBe(200)
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible({
    timeout: 15000,
  })
  return { ctx, page }
}
async function open(page, key = KEY) {
  const input = page.getByLabel('Smart search', { exact: true })
  await input.fill(key)
  await input.press('Enter')
  await expect(page.locator('.booking-summary-card')).toContainText(key.replace(/^CW/, 'CW '))
}
const editor = (page) => page.locator('.note-form .invoice-panel')
async function add(page, value) {
  const input = editor(page).locator('input:not([type=checkbox])')
  await input.fill(value)
  await input.press('Enter')
}
async function saveInvoices(page) {
  const response = page.waitForResponse(
    (r) => r.request().method() === 'PUT' && new URL(r.url()).pathname.endsWith('/invoices'),
  )
  await editor(page).getByRole('button', { name: 'Save invoices', exact: true }).click()
  const r = await response
  expect(r.status()).toBe(200)
  await expect(page.locator('.outbox-panel')).toHaveCount(0)
  return (await r.json()).snapshot
}
try {
  const agent = await login('agent'),
    other = await login('other'),
    qc = await login('qc')
  await open(agent.page)
  await agent.page.locator('.status-options button').filter({ hasText: 'Done' }).click()
  await expect(agent.page.locator('.save-note')).toBeDisabled()
  await agent.page.keyboard.press('Alt+i')
  await expect(editor(agent.page).locator('input:not([type=checkbox])')).toBeFocused()
  await add(agent.page, 'inv100, inv200; inv100')
  await expect(editor(agent.page).locator('.invoice-chip')).toHaveCount(2)
  await expect(
    editor(agent.page).getByLabel('No invoice Number', { exact: true }),
  ).toBeDisabled()
  await agent.page.getByLabel('Note', { exact: true }).fill('Done with both invoice numbers')
  const saved = agent.page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname.endsWith('/notes'),
  )
  await agent.page.locator('.save-note').click()
  const first = await saved
  expect(first.status()).toBe(200)
  const before = (await first.json()).snapshot
  await expect(agent.page.locator('.outbox-panel')).toHaveCount(0)
  await expect(agent.page.locator('.timeline-invoice-change').first()).toContainText(
    '+ INV100, INV200',
  )
  await open(other.page)
  expect(
    await editor(other.page)
      .getByRole('button', { name: 'Remove invoice INV100', exact: true })
      .count(),
  ).toBe(0)
  await add(other.page, 'INV300')
  const after = await saveInvoices(other.page)
  expect(after.updated_at).toBe(before.updated_at)
  expect(after.last_agent).toEqual(before.last_agent)
  expect(after.is_done).toBe(true)
  await expect(agent.page.locator('.booking-summary-card .invoice-chip')).toHaveCount(3)
  await open(qc.page)
  qc.page.once('dialog', (dialog) => dialog.accept())
  await editor(qc.page)
    .getByRole('button', { name: 'Remove invoice INV100', exact: true })
    .click()
  await saveInvoices(qc.page)
  await expect(agent.page.locator('.booking-summary-card .invoice-chip')).toHaveCount(2)
  await open(agent.page, 'CW2154654-RDU-2610')
  await agent.page.getByRole('button', { name: 'This is a new booking', exact: true }).click()
  await agent.page.locator('.status-options button').filter({ hasText: 'Bundle' }).click()
  await agent.page
    .getByLabel('Note', { exact: true })
    .fill('Check matching invoice on the adjacent month')
  await add(agent.page, 'INV200')
  const created = agent.page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname.endsWith('/notes'),
  )
  await agent.page.locator('.save-note').click()
  expect((await created).status()).toBe(200)
  await expect(editor(agent.page).locator('.booking-warning')).toContainText('INV200')
  await expect(editor(agent.page).getByRole('link')).toHaveAttribute('href', '/summary/' + KEY)
  await agent.page.getByLabel('Smart search', { exact: true }).fill('INV:inv200')
  await expect(agent.page.locator('.invoice-search-hit')).toHaveCount(2)
  await open(agent.page)
  await agent.page.locator('.status-options button').filter({ hasText: 'Bundle' }).click()
  await agent.page
    .getByLabel('Note', { exact: true })
    .fill('Preserve this note while invoice sends separately')
  const pattern = '**/api/v1/bookings/*/invoices'
  await agent.ctx.route(pattern, (route) =>
    route.request().method() === 'PUT'
      ? route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ code: 'SERVICE_BUSY', message: 'Test retry' }),
        })
      : route.continue(),
  )
  await add(agent.page, 'INV400')
  await editor(agent.page).getByRole('button', { name: 'Save invoices', exact: true }).click()
  await expect(agent.page.locator('.outbox-panel')).toHaveCount(1)
  await expect(agent.page.getByLabel('Note', { exact: true })).toHaveValue(
    'Preserve this note while invoice sends separately',
  )
  await agent.page.reload()
  await expect(agent.page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible(
    { timeout: 15000 },
  )
  await expect(agent.page.locator('.outbox-panel')).toHaveCount(1)
  await open(agent.page)
  await agent.ctx.unroute(pattern)
  await agent.page.locator('.outbox-panel summary').click()
  await agent.page
    .locator('.outbox-panel')
    .getByRole('button', { name: 'Retry', exact: true })
    .click()
  await expect(agent.page.locator('.outbox-panel')).toHaveCount(0, {
    timeout: 15000,
  })
  await expect(agent.page.getByLabel('Note', { exact: true })).toHaveValue(
    'Preserve this note while invoice sends separately',
  )
  await expect(agent.page.locator('.booking-summary-card .invoice-chip')).toHaveCount(3)
  await expect(agent.page.locator('.work-card > .booking-timeline .timeline-item')).toHaveCount(
    2,
  )
  await qc.page.goto('http://localhost:5173/reports')
  const report = qc.page.locator('.invoice-report-panel')
  await expect(report).toContainText('Invoices per booking')
  await report.getByLabel('Invoice period', { exact: true }).fill('2026-09')
  await report.getByRole('button', { name: 'Load invoices', exact: true }).click()
  await expect(report).toContainText('Sep 2026')
  const download = qc.page.waitForEvent('download')
  await report.getByRole('button', { name: 'Export invoices (Excel)', exact: true }).click()
  await (await download).saveAs(path.join(artifacts, 'invoices-2609.xlsx'))
  await report.getByRole('link').click()
  await expect(qc.page).toHaveURL(/invoice_state=unknown/)
  await agent.page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => agent.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true)
  await agent.page.screenshot({
    path: path.join(artifacts, 'invoices-mobile.png'),
    fullPage: true,
  })
  expect(errors).toEqual([])
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally {
  await browser.close()
}
