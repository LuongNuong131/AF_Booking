import { chromium, expect } from '@playwright/test'
const browser = await chromium.launch({
  headless: true,
  ...(process.env.BOOKING_CHROMIUM_PATH
    ? { executablePath: process.env.BOOKING_CHROMIUM_PATH }
    : {}),
})
const KEY = 'CW2154654-RDU-2609',
  DISPLAY = 'CW 2154654-RDU-2609',
  errors = []
function deferred() {
  let resolve
  const promise = new Promise((done) => (resolve = done))
  return { promise, resolve }
}
async function login(username) {
  const context = await browser.newContext(),
    page = await context.newPage()
  page.on('pageerror', (e) => errors.push(e.name))
  await expect(async () => {
    await page.goto('http://localhost:5173')
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible()
  return { page, context }
}
async function open(page) {
  await page.getByLabel('Smart search', { exact: true }).fill(KEY)
  await page.getByLabel('Smart search', { exact: true }).press('Enter')
  await expect(page.locator('.booking-summary-card')).toContainText(DISPLAY)
}
try {
  const a = await login('agent'),
    page = a.page
  const lookup = '**/api/v1/bookings/lookup?*',
    blocked = deferred()
  const delayLookup = async (route) => {
    await blocked.promise
    await route.continue().catch(() => {})
  }
  await page.route(lookup, delayLookup)
  await page.getByLabel('Smart search', { exact: true }).fill(KEY)
  await expect(page.getByText('Still working…', { exact: true })).toBeVisible({ timeout: 5000 })
  await expect(
    page.getByText('This is taking too long. Please try again.', { exact: true }),
  ).toBeVisible({ timeout: 10000 })
  await expect(page.getByLabel('Smart search', { exact: true })).toBeEditable()
  await page.unroute(lookup, delayLookup)
  blocked.resolve()
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.locator('.booking-summary-card')).toContainText(DISPLAY)
  await page.locator('.booking-summary-card').click()
  await page.keyboard.press('/')
  await expect(page.getByLabel('Smart search', { exact: true })).toBeFocused()
  for (let n = 1; n <= 5; n++) {
    await page.keyboard.press('Alt+' + n)
    await expect(page.locator('.status-options button').nth(n - 1)).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  }
  await page.keyboard.press('Alt+4')
  const posts = '**/api/v1/bookings/*/notes',
    attempts = [],
    held = deferred()
  let first = true
  const delayAcknowledgement = async (route) => {
    attempts.push(route.request().postDataJSON().client_request_id)
    if (first) {
      first = false
      const response = await route.fetch()
      await held.promise
      await route.fulfill({ response }).catch(() => {})
    } else await route.continue()
  }
  await page.route(posts, delayAcknowledgement)
  await page.getByLabel('Note', { exact: true }).fill('Delayed HTTP acknowledgement')
  await page.keyboard.press('Control+Enter')
  await expect(
    page.locator('.timeline-item').filter({ hasText: 'Delayed HTTP acknowledgement' }),
  ).toBeVisible()
  await expect(page.locator('.outbox-panel')).toBeVisible()
  // The first POST committed; its response is withheld past the real 15-second client budget.
  await expect.poll(() => attempts.length, { timeout: 25000 }).toBeGreaterThanOrEqual(2)
  held.resolve()
  await expect(page.locator('.outbox-panel')).toHaveCount(0, { timeout: 10000 })
  expect(new Set(attempts).size).toBe(1)
  await expect(
    page.locator('.timeline-item').filter({ hasText: 'Delayed HTTP acknowledgement' }),
  ).toHaveCount(1)
  await page.unroute(posts, delayAcknowledgement)
  await page.reload()
  await open(page)
  await expect(
    page.locator('.timeline-item').filter({ hasText: 'Delayed HTTP acknowledgement' }),
  ).toHaveCount(1)
  await page.keyboard.press('Alt+1')
  await page.getByLabel('No invoice Number', { exact: true }).check()
  await page.getByLabel('Note', { exact: true }).fill('Completed before supplier follow-up')
  await page.keyboard.press('Control+Enter')
  await expect(page.locator('.outbox-panel')).toHaveCount(0)
  const b = await login('other')
  await open(b.page)
  await expect(b.page.getByText(/already marked this booking Done/)).toBeVisible()
  await b.page.keyboard.press('Alt+3')
  await b.page.getByLabel('Note', { exact: true }).fill('Parking after completed record')
  await b.page.keyboard.press('Control+Enter')
  await expect(b.page.locator('.outbox-panel')).toHaveCount(0)
  await expect(b.page.locator('.booking-summary-card')).toContainText('Parking')
  await expect(b.page.locator('.timeline-item')).toHaveCount(4)
  await expect(
    b.page.locator('.timeline-item').filter({ hasText: 'Completed before supplier follow-up' }),
  ).toHaveCount(1)
  await page.reload()
  await open(page)
  await page.keyboard.press('Alt+4')
  await b.page.keyboard.press('Alt+4')
  await page.getByLabel('Note', { exact: true }).fill('Concurrent A draft survives')
  await b.page.getByLabel('Note', { exact: true }).fill('Concurrent B saved first')
  const aSeen = deferred(),
    bSeen = deferred(),
    releaseA = deferred(),
    releaseB = deferred()
  const holdA = async (route) => {
    aSeen.resolve()
    await releaseA.promise
    await route.continue()
  }
  const holdB = async (route) => {
    bSeen.resolve()
    await releaseB.promise
    await route.continue()
  }
  await page.route(posts, holdA)
  await b.page.route(posts, holdB)
  await Promise.all([
    page.getByRole('button', { name: /^Save update/ }).click(),
    b.page.getByRole('button', { name: /^Save update/ }).click(),
  ])
  await Promise.all([aSeen.promise, bSeen.promise])
  const saved = b.page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname.endsWith('/notes'),
  )
  releaseB.resolve()
  expect((await saved).status()).toBe(200)
  releaseA.resolve()
  await expect(page.getByRole('dialog')).toContainText('Concurrent B saved first')
  await page
    .getByRole('button', { name: 'Use latest version and keep my draft', exact: true })
    .click()
  await expect(page.getByLabel('Note', { exact: true })).toHaveValue(
    'Concurrent A draft survives',
  )
  expect(errors).toEqual([])
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally {
  await browser.close()
}
