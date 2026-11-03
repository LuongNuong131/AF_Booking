import { chromium, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { createInterface } from 'node:readline'
import path from 'node:path'
const artifacts = process.env.BOOKING_E2E_ARTIFACTS
await mkdir(artifacts, { recursive: true })
const input = createInterface({ input: process.stdin })
let acknowledge
input.on('line', (line) => {
  if (JSON.parse(line).ok) {
    acknowledge?.()
    acknowledge = null
  }
})
async function command(action) {
  const result = new Promise((resolve) => {
    acknowledge = resolve
  })
  process.stdout.write(JSON.stringify({ action }) + '\n')
  await result
}
const browser = await chromium.launch({
  headless: true,
  ...(process.env.BOOKING_CHROMIUM_PATH
    ? { executablePath: process.env.BOOKING_CHROMIUM_PATH }
    : {}),
})
const errors = [],
  KEY = 'CW2154654-RDU-2609',
  TYPO = 'CW2154655-RDU-2609'
async function login(username) {
  const ctx = await browser.newContext({
      viewport: { width: 1440, height: 1050 },
      reducedMotion: 'reduce',
      colorScheme: 'light',
    }),
    page = await ctx.newPage()
  page.on('pageerror', (error) => errors.push(error.name))
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
async function open(page, key) {
  const input = page.getByLabel('Smart search', { exact: true })
  await input.fill(key)
  await input.press('Enter')
  await expect(page.locator('.booking-summary-card')).toContainText(key.replace(/^CW/, 'CW '))
}
async function write(page, note, status = 'Bundle') {
  await page.locator('.status-options button').filter({ hasText: status }).click()
  await page.getByLabel('Note', { exact: true }).fill(note)
}
async function save(page, status = 200) {
  const response = page.waitForResponse(
    (r) =>
      r.request().method() === 'POST' &&
      /\/bookings\/[^/]+\/notes$/.test(new URL(r.url()).pathname),
  )
  await page.getByRole('button', { name: /^Save update/ }).click()
  expect((await response).status()).toBe(status)
  if (status === 200) await expect(page.locator('.outbox-panel')).toHaveCount(0)
}
try {
  const agent = await login('agent'),
    admin = await login('admin'),
    page = agent.page
  await open(page, TYPO)
  await expect(page.locator('.booking-new-confirm')).toContainText('Did you mean:')
  await page.getByLabel('Supplier name', { exact: true }).fill('Intentional new supplier')
  await write(page, 'Review this possible typo')
  await expect(page.locator('.save-note')).toBeDisabled()
  await page.getByLabel('Smart search', { exact: true }).press('ArrowDown')
  await expect(page.locator('.booking-new-confirm [data-search-result]').first()).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('.booking-summary-card')).toContainText('CW 2154654-RDU-2609')
  await expect(page.locator('.booking-new-confirm')).toHaveCount(0)
  await write(page, 'Checked supplier mail')
  await save(page)
  await expect(page.locator('.timeline-item').first()).toContainText('Checked supplier mail')
  await write(page, ' CHECKED    SUPPLIER\nMAIL ')
  await save(page, 409)
  const duplicate = page.getByRole('dialog', { name: 'Review duplicate note', exact: true })
  await expect(duplicate).toContainText('You sent an identical note')
  await duplicate.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue('CHECKED    SUPPLIER\nMAIL')
  await save(page, 409)
  const confirmed = page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname.endsWith('/notes'),
  )
  await duplicate.getByRole('button', { name: 'Send anyway', exact: true }).click()
  expect((await confirmed).status()).toBe(200)
  await expect(page.locator('.outbox-panel')).toHaveCount(0)
  await expect(page.locator('.work-card > .booking-timeline .timeline-item')).toHaveCount(3)
  await open(page, 'CW2154654-RDU-2610')
  await write(page, 'Waiting for supplier', 'Rejection')
  await expect(page.locator('.save-note')).toBeDisabled()
  await page.getByRole('button', { name: 'This is a new booking', exact: true }).click()
  await save(page)
  const suggestion = page.getByRole('button', { name: /^Remind in 3 days/ })
  await expect(suggestion).toBeVisible()
  await suggestion.click()
  await expect(
    page.getByRole('dialog').getByRole('button', { name: '+3 days', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  await page.keyboard.press('Escape')
  await command('integrity_drift')
  await admin.page.goto('http://localhost:5173/admin/integrity')
  await expect(admin.page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible({
    timeout: 15000,
  })
  await admin.page.getByRole('button', { name: 'Run check', exact: true }).click()
  const card = admin.page.locator('.integrity-history-card').first()
  await expect(card).toContainText('Completed', { timeout: 15000 })
  await expect(card).toContainText('Mismatched: 1')
  await expect(card).toContainText('Fixed: 0')
  await card.getByRole('button', { name: 'Mismatch details', exact: true }).click()
  const details = admin.page.getByRole('dialog', { name: 'Mismatch details', exact: true })
  await expect(details).toContainText('Broken snapshot')
  await expect(details).toContainText('last_position')
  await admin.page.keyboard.press('Escape')
  await card.getByRole('button', { name: 'Fix mismatched bookings', exact: true }).click()
  await admin.page
    .getByRole('dialog', { name: 'Confirm snapshot repairs', exact: true })
    .getByRole('button', { name: 'Start repairs', exact: true })
    .click()
  await expect(card).toContainText('Completed', { timeout: 15000 })
  await expect(card).toContainText('Fixed: 1')
  await open(page, KEY)
  await expect(page.locator('.booking-summary-card')).toContainText('Bundle')
  await expect(page.locator('.booking-summary-card')).not.toContainText('Broken snapshot')
  await admin.page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => admin.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true)
  await admin.page.screenshot({
    path: path.join(artifacts, 'integrity-mobile.png'),
    fullPage: true,
  })
  await page.goto('http://localhost:5173/admin/integrity')
  await expect(page).toHaveURL('http://localhost:5173/')
  expect(errors).toEqual([])
  await agent.ctx.close()
  await admin.ctx.close()
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally {
  input.close()
  await browser.close()
}
