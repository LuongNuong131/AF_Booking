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
  const wait = new Promise((resolve) => {
    acknowledge = resolve
  })
  process.stdout.write(JSON.stringify({ action }) + '\n')
  await wait
}
const browser = await chromium.launch({
  headless: true,
  ...(process.env.BOOKING_CHROMIUM_PATH
    ? { executablePath: process.env.BOOKING_CHROMIUM_PATH }
    : {}),
})
const CW = 'CW2154927',
  KEY = `${CW}-YUL-2608`,
  DISPLAY = 'CW 2154927-YUL-2608',
  errors = [],
  requests = []
async function login(username = 'agent') {
  const ctx = await browser.newContext({
      viewport: { width: 1440, height: 1050 },
      reducedMotion: 'reduce',
      colorScheme: 'light',
    }),
    page = await ctx.newPage()
  page.on('pageerror', (error) => errors.push(error.name))
  page.on('request', (request) => {
    if (request.method() === 'GET') requests.push(new URL(request.url()).pathname)
  })
  await expect(async () => {
    await page.goto('http://localhost:5173')
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible()
  return { ctx, page }
}
try {
  const { ctx, page } = await login(),
    search = page.getByLabel('Smart search', { exact: true })
  await expect(search).toBeFocused()
  await expect(search).toHaveAttribute(
    'placeholder',
    'Search booking, CW number, station code or supplier…',
  )
  await search.fill('YUL')
  await expect(page.locator('.station-section')).toHaveCount(2)
  await expect(page.locator('.station-section').first()).toContainText('Hotel')
  await expect(page.locator('.station-section').last()).toContainText('Transportation')
  await expect(page.locator('.station-section').last()).toContainText('Montreal Crew Shuttle')
  await search.press('ArrowDown')
  await expect(page.locator('.station-section').first().locator('.folder-card')).toBeFocused()
  await page.keyboard.press('Enter')
  try {
    await expect(page.locator('.supplier-folder .month-row')).toHaveCount(3)
  } catch (error) {
    await page.screenshot({
      path: path.join(artifacts, 'folder-keyboard-failure.png'),
      fullPage: true,
    })
    process.stderr.write(
      JSON.stringify({ url: page.url(), errors, requests: requests.slice(-8) }) + '\n',
    )
    throw error
  }
  await expect(page.locator('.folder-breadcrumbs')).toContainText('Search')
  await expect(page.locator('.folder-breadcrumbs')).toContainText(CW)
  await expect(page.locator('.supplier-folder')).toContainText('1 stale month(s)')
  await expect(page.getByRole('button', { name: 'Edit supplier', exact: true })).toHaveCount(0)
  const before = requests.length
  await command('folder_update')
  await expect(page.locator('.supplier-folder .folder-open')).toHaveText('2 open')
  await expect(page.locator('.supplier-folder .month-row').first()).toContainText('Done')
  await expect
    .poll(() => requests.slice(before).filter((p) => p === `/api/v1/folders/${CW}`).length)
    .toBeGreaterThan(0)
  expect(
    requests.slice(before).filter((p) => p === '/api/v1/search' || p === '/api/v1/folders'),
  ).toHaveLength(0)
  await page.getByRole('button', { name: '+ New month', exact: true }).click()
  await page.getByLabel('Period', { exact: true }).fill('2026-10')
  await page.getByRole('button', { name: 'Open month', exact: true }).click()
  await expect(page.locator('.booking-summary-card')).toContainText('CW 2154927-YUL-2610')
  await expect(page.locator('.booking-summary-card')).toContainText('Hotellus Montreal')
  await expect(page.locator('.supplier-setup')).toHaveCount(0)
  await search.press('Escape')
  await expect(page.locator('.supplier-folder .month-row')).toHaveCount(3)
  const beforeBack = requests.filter((p) => p === '/api/v1/search').length
  await search.press('Backspace')
  await expect(page.locator('.station-section')).toHaveCount(2)
  // The invalidated SWR result is visible immediately and is revalidated once.
  await expect
    .poll(() => requests.filter((p) => p === '/api/v1/search').length)
    .toBeLessThanOrEqual(beforeBack + 1)
  await search.fill('double tree')
  await expect(page.locator('.smart-results .folder-card')).toHaveCount(1)
  await search.fill('CW 2154927-YUL-2608')
  await expect(page.locator('.booking-summary-card')).toContainText(DISPLAY)
  await expect(search).toHaveValue(DISPLAY)
  expect(requests.filter((p) => p === '/api/v1/search').length).toBeLessThan(8)
  await search.fill('CW2154927-2608')
  await expect(page.getByRole('button', { name: 'Use this booking', exact: true })).toBeVisible()
  const lookups = requests.filter((p) => p === '/api/v1/bookings/lookup').length
  await search.press('Enter')
  await expect(page.locator('.booking-summary-card')).toContainText(DISPLAY)
  expect(requests.filter((p) => p === '/api/v1/bookings/lookup').length).toBe(lookups)
  await search.fill('CW2154927-YUL-2613')
  await expect(
    page.getByText('Invalid booking number. Expected format: CW 1234567-YUL-2608.', {
      exact: true,
    }),
  ).toBeVisible()
  await search.fill('CW2154927-RDU-2608')
  await expect(page.locator('.resolution-panel')).toContainText('belongs to station YUL')
  await page.getByRole('button', { name: 'Use this booking', exact: true }).click()
  await expect(page.locator('.booking-summary-card')).toContainText(DISPLAY)
  await search.fill('CW9876123-2610')
  await expect(
    page.getByText('New CW number. Enter the station code to continue.', { exact: true }),
  ).toBeVisible()
  await expect(page.locator('.note-form')).toHaveCount(0)
  await page.getByLabel('Station code', { exact: true }).fill('YUL')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.locator('.supplier-setup')).toBeVisible()
  await page.locator('.status-options button').filter({ hasText: 'Bundle' }).click()
  await page.getByLabel('Supplier name', { exact: true }).fill('AB')
  await expect(page.locator('.save-note')).toBeDisabled()
  await page.getByLabel('Supplier name', { exact: true }).fill('New Crew Hotel')
  await expect(page.locator('.save-note')).toBeDisabled()
  await page.getByRole('button', { name: 'This is a new booking', exact: true }).click()
  await expect(page.locator('.save-note')).toBeEnabled()
  await search.fill('YUL-2608')
  await expect(page.locator('.smart-results .month-row')).toHaveCount(2)
  await page.getByRole('link', { name: 'Summary', exact: true }).click()
  await page.getByRole('button', { name: 'Folders', exact: true }).click()
  await expect(page.locator('.summary-folder-grid .folder-card')).toHaveCount(3)
  await page.getByLabel('Station', { exact: true }).fill('yul')
  await expect(page).toHaveURL(/station_code=YUL/)
  await expect(page.locator('.summary-folder-grid .folder-card')).toHaveCount(2)
  await page.getByLabel('Type', { exact: true }).selectOption('hotel')
  await expect(page).toHaveURL(/supplier_type=hotel/)
  await expect(page.locator('.summary-folder-grid .folder-card')).toHaveCount(1)
  const savedUrl = page.url()
  await page.locator('.summary-folder-grid .folder-card').click()
  await expect(page).toHaveURL(new RegExp(`/summary/folders/${CW}`))
  await page.reload()
  await expect(page.locator('.month-row')).toHaveCount(3)
  await page.locator('.month-row').filter({ hasText: DISPLAY }).click()
  await expect(page).toHaveURL(new RegExp(`/summary/${KEY}`))
  await page.getByRole('button', { name: 'Back to folder', exact: true }).click()
  await expect(page.locator('.month-row')).toHaveCount(3)
  await page.getByRole('button', { name: '← Back to Summary', exact: true }).click()
  await expect(page).toHaveURL(savedUrl)
  await page.screenshot({ path: path.join(artifacts, 'folders-summary.png'), fullPage: true })
  await page.getByRole('link', { name: 'Home', exact: true }).click()
  await page.getByRole('button', { name: 'Clear booking', exact: true }).click()
  await expect(page.locator('.recent-folders')).toContainText(CW)
  await search.fill(CW)
  await expect(page.locator('.smart-results .folder-card')).toBeVisible()
  await page.locator('.smart-results .folder-card').click()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true)
  await page.screenshot({ path: path.join(artifacts, 'folders-mobile.png'), fullPage: true })
  const qc = await login('qc')
  await qc.page.getByLabel('Smart search', { exact: true }).fill(CW)
  await qc.page.locator('.smart-results .folder-card').click()
  await qc.page.getByRole('button', { name: 'Edit supplier', exact: true }).click()
  await qc.page.getByLabel('Supplier name', { exact: true }).fill('Renamed Montreal Hotel')
  await qc.page.getByRole('button', { name: 'Save supplier', exact: true }).click()
  await expect(qc.page.locator('.supplier-folder .folder-supplier')).toHaveText(
    'Renamed Montreal Hotel',
  )
  await qc.page.getByLabel('Smart search', { exact: true }).press('Escape')
  await qc.page.getByLabel('Smart search', { exact: true }).fill('renamed montreal')
  await expect(qc.page.locator('.smart-results .folder-card')).toContainText(
    'Renamed Montreal Hotel',
  )
  expect(errors).toEqual([])
  await qc.ctx.close()
  await ctx.close()
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally {
  input.close()
  await browser.close()
}
