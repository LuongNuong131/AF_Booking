// Real two-user workflow. API interception is limited to response timing for one retry check.
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
const errors = []
const KEY = 'CW2154654-RDU-2609',
  DISPLAY = 'CW 2154654-RDU-2609'
async function start(username) {
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1100 },
    reducedMotion: 'reduce',
    colorScheme: 'light',
  })
  const page = await context.newPage()
  page.on('pageerror', (error) => errors.push(error.name))
  await expect(async () => {
    await page.goto('http://localhost:5173')
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  }).toPass({ timeout: 15000 })
  await page.getByRole('textbox', { name: 'Username', exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Home', exact: true })).toBeVisible()
  return { context, page }
}
async function open(page, key = KEY) {
  const input = page.getByLabel('Smart search', { exact: true })
  await input.fill(key)
  await input.press('Enter')
  await expect(page.locator('.booking-summary-card')).toContainText(
    key === KEY ? DISPLAY : key.replace(/^CW/, 'CW '),
  )
  await expect(page.getByRole('form', { name: 'Booking note' })).toBeVisible()
}
async function write(page, message, status = 'Bundle') {
  await page
    .getByRole('button', { name: new RegExp(`^${status}`) })
    .first()
    .click()
  await page.getByLabel('Note', { exact: true }).fill(message)
}
async function save(page) {
  const response = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/bookings\/[^/]+\/notes$/.test(new URL(response.url()).pathname),
  )
  await page.getByRole('button', { name: /^Save update/ }).click()
  expect((await response).status()).toBe(200)
  await expect(page.locator('.note-form .save-note')).not.toContainText('Saving…')
  await expect(page.locator('.notice-stack')).toContainText('Booking update saved.')
}
try {
  const a = await start('agent'),
    b = await start('other')
  await a.page.locator('.mine-booking').filter({ hasText: DISPLAY }).click()
  await expect(a.page.locator('.booking-summary-card')).toContainText(DISPLAY)
  await expect(a.page.getByLabel('Smart search', { exact: true })).toHaveValue(DISPLAY)
  await a.page.getByLabel('Smart search', { exact: true }).fill('cw 2154654-2609')
  await expect(a.page.getByRole('button', { name: 'Use this booking' })).toBeVisible()
  let extraLookups = 0
  const countLookup = (request) => {
    if (new URL(request.url()).pathname === '/api/v1/bookings/lookup') extraLookups++
  }
  a.page.on('request', countLookup)
  await a.page.getByLabel('Smart search', { exact: true }).press('Enter')
  await expect(a.page.locator('.booking-summary-card')).toContainText(DISPLAY)
  expect(extraLookups).toBe(0)
  a.page.off('request', countLookup)
  await write(a.page, 'Draft stays while a teammate updates')
  await open(b.page)
  await expect(b.page.locator('.lock-badge')).toContainText('Agent is working on this booking')
  await write(b.page, 'Other agent took over')
  await save(b.page)
  await expect(a.page.locator('.mine-booking').filter({ hasText: DISPLAY })).toHaveCount(0)
  await expect(b.page.locator('.mine-booking').first()).toContainText(DISPLAY)
  await expect(a.page.locator('.booking-update-banner')).toContainText('New update available.')
  await expect(a.page.getByLabel('Note', { exact: true })).toHaveValue(
    'Draft stays while a teammate updates',
  )
  // Saving the stale expected_version must require review and preserve the draft.
  await a.page.getByRole('button', { name: /^Save update/ }).click()
  await expect(a.page.getByRole('dialog')).toContainText('Other agent took over')
  await a.page.getByRole('button', { name: 'Use latest version and keep my draft' }).click()
  await expect(a.page.getByLabel('Note', { exact: true })).toHaveValue(
    'Draft stays while a teammate updates',
  )
  await save(a.page)
  await expect(b.page.locator('.mine-booking').filter({ hasText: DISPLAY })).toHaveCount(0)
  await expect(a.page.locator('.mine-booking').first()).toContainText(DISPLAY)
  await expect(a.page.getByLabel('Smart search', { exact: true })).toBeFocused()
  await write(a.page, 'Persistent draft after reload')
  await expect
    .poll(async () =>
      a.page.evaluate(
        () =>
          JSON.parse(localStorage.getItem('booking.drafts.v1.3') || '{}')['CW2154654-RDU-2609']
            ?.note,
      ),
    )
    .toBe('Persistent draft after reload')
  await a.page.reload()
  await open(a.page)
  await expect(a.page.getByLabel('Note', { exact: true })).toHaveValue(
    'Persistent draft after reload',
  )
  await a.page.getByRole('button', { name: 'Discard draft' }).click()
  await expect(a.page.getByLabel('Note', { exact: true })).toHaveValue('')
  await a.page.getByRole('button', { name: /^Rejection/ }).click()
  await expect(a.page.getByRole('button', { name: /^Save update/ })).toBeDisabled()
  await expect(
    a.page.getByText('A note is required for this status.', { exact: true }),
  ).toBeVisible()
  await a.context.setOffline(true)
  await a.page.getByLabel('Note', { exact: true }).fill('Offline draft retained')
  await expect(a.page.locator('.offline-save')).toBeVisible()
  await expect(a.page.getByRole('button', { name: /^Save update/ })).toBeEnabled()
  await a.context.setOffline(false)
  await expect(a.page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible({
    timeout: 20000,
  })
  await expect(a.page.getByLabel('Note', { exact: true })).toHaveValue('Offline draft retained')
  await a.page.getByRole('button', { name: 'Discard draft' }).click()
  await a.page.screenshot({ path: path.join(artifacts, 'workspace-light.png'), fullPage: true })
  // A new CW with no station resolves through the required station and Supplier steps.
  await a.page.getByLabel('Smart search', { exact: true }).fill('CW9876543-2610')
  await a.page.getByLabel('Smart search', { exact: true }).press('Enter')
  await a.page.getByLabel('Station code', { exact: true }).fill('yul')
  await a.page.getByRole('button', { name: 'Continue', exact: true }).click()
  await a.page.getByLabel('Supplier name', { exact: true }).fill('New Airport Hotel')
  await write(a.page, 'First update for a new supplier')
  await save(a.page)
  await expect(a.page.locator('.booking-summary-card')).toContainText('New Airport Hotel')
  await a.page.getByRole('button', { name: /^Done/ }).click()
  await expect(a.page.getByRole('button', { name: /^Save update/ })).toBeDisabled()
  await a.page.getByLabel('No invoice Number', { exact: true }).check()
  await save(a.page)
  await a.page.getByRole('link', { name: 'Summary', exact: true }).click()
  await a.page
    .getByRole('textbox', { name: 'Search bookings', exact: true })
    .fill('CW 2154654-2609')
  await expect(a.page.locator('.booking-table tbody tr')).toHaveCount(1)
  await expect(a.page).toHaveURL(/q=CW\+2154654-2609/)
  await a.page.getByLabel('Status', { exact: true }).selectOption('BUNDLE')
  await expect(a.page).toHaveURL(/status_code=BUNDLE/)
  const returnUrl = a.page.url()
  await a.page.locator('.table-booking-link').click()
  await expect(a.page).toHaveURL(/\/summary\/CW2154654-RDU-2609/)
  await expect(a.page.locator('.booking-timeline .timeline-item')).toHaveCount(3)
  let backReads = 0
  const countBack = (request) => {
    if (new URL(request.url()).pathname === '/api/v1/bookings') backReads++
  }
  a.page.on('request', countBack)
  await a.page.getByRole('button', { name: '← Back to Summary' }).click()
  await expect(a.page).toHaveURL(returnUrl)
  await expect(a.page.locator('.booking-table tbody tr')).toHaveCount(1)
  expect(backReads).toBe(0)
  a.page.off('request', countBack)
  await a.page.getByRole('button', { name: 'Clear filters' }).click()
  await expect(a.page.locator('.booking-table tbody tr')).toHaveCount(2)
  // Change only a visible Summary row; the whole page endpoint must not refetch.
  let pageReads = 0
  const countPage = (request) => {
    if (new URL(request.url()).pathname === '/api/v1/bookings') pageReads++
  }
  a.page.on('request', countPage)
  await b.page.locator('.booking-update-banner .text-button').click()
  await write(b.page, 'Visible row changed over realtime')
  await save(b.page)
  await expect(
    a.page.locator('.booking-table tbody tr').filter({ hasText: DISPLAY }),
  ).toContainText('Visible row changed over realtime')
  expect(pageReads).toBe(0)
  a.page.off('request', countPage)
  await a.page.screenshot({ path: path.join(artifacts, 'summary-light.png'), fullPage: true })
  await a.page.getByRole('link', { name: 'Profile', exact: true }).click()
  await a.page.getByRole('combobox', { name: 'Appearance', exact: true }).selectOption('dark')
  await a.page.getByRole('link', { name: 'Home', exact: true }).click()
  await open(a.page)
  await a.page.screenshot({ path: path.join(artifacts, 'workspace-dark.png'), fullPage: true })
  await a.page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => a.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true)
  await a.page.evaluate(() => window.scrollTo(0, 0))
  await a.page.screenshot({ path: path.join(artifacts, 'workspace-mobile.png'), fullPage: true })
  await expect
    .poll(() => a.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true)
  expect(errors).toEqual([])
  await a.context.close()
  await b.context.close()
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally {
  await browser.close()
}
