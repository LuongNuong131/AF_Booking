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
const errors = [],
  KEY = 'CW2154654-RDU-2609'
async function login(username) {
  const ctx = await browser.newContext({
      viewport: { width: 1440, height: 1050 },
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
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible({
    timeout: 15000,
  })
  return { ctx, page }
}
async function open(page) {
  const input = page.getByLabel('Smart search', { exact: true })
  await input.fill(KEY)
  await input.press('Enter')
  await expect(page.locator('.booking-summary-card')).toContainText('CW 2154654-RDU-2609')
}
async function save(page, text) {
  await page.locator('.status-options button').filter({ hasText: 'Bundle' }).click()
  await page.getByLabel('Note', { exact: true }).fill(text)
  const response = page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname.endsWith('/notes'),
  )
  await page.locator('.save-note').click()
  expect((await response).status()).toBe(200)
  await expect(page.locator('.outbox-panel')).toHaveCount(0)
}
try {
  const a = await login('admin'),
    b = await login('agent'),
    c = await login('other')
  await open(a.page)
  await open(b.page)
  await open(c.page)
  await a.page.locator('.work-card > .watch-button').click()
  await expect(a.page.locator('.work-card > .watch-button')).toHaveAttribute('aria-pressed', 'true')
  for (let i = 1; i <= 3; i++) await save(b.page, `Team update ${i}`)
  await a.page.locator('.notifications-menu summary').click()
  await expect(a.page.locator('.notification-list li')).toHaveCount(1)
  await expect(a.page.locator('.notification-list')).toContainText('3 updates')
  await a.page.locator('.notifications-menu summary').click()
  // Ctrl+K works while editing; Agent commands omit administration and export.
  await b.page.getByLabel('Note', { exact: true }).fill('Keep this unfinished draft')
  await b.page.getByLabel('Note', { exact: true }).press('Control+k')
  const palette = b.page.getByRole('dialog', { name: 'Command palette', exact: true })
  await expect(palette).toBeVisible()
  await expect(palette).not.toContainText('Go to Admin')
  await expect(palette).not.toContainText('Export today')
  await palette.getByRole('combobox').fill('cw 2154654 - rdu - 2609')
  await expect(palette.getByRole('option').first()).toContainText(
    'Open booking CW 2154654-RDU-2609',
  )
  await palette.getByRole('combobox').press('Enter')
  await expect(palette).not.toBeVisible()
  await expect(b.page.locator('.booking-summary-card')).toContainText('CW 2154654-RDU-2609')
  await b.page.getByLabel('Assign to', { exact: true }).fill('Other')
  await b.page.locator('.assignee-results button').filter({ hasText: 'Other' }).click()
  await b.page.getByLabel('Optional message', { exact: true }).fill('Please check supplier mail')
  await save(b.page, 'Handover to Other')
  const assignedTab = c.page.getByRole('button', { name: /Assigned to me/ })
  await expect(assignedTab).toContainText('1')
  await assignedTab.click()
  await expect(c.page.locator('.assignment-row')).toContainText('Please check supplier mail')
  // Navigation shortcuts never run while typing in the note editor.
  const note = c.page.getByLabel('Note', { exact: true })
  await note.fill('jkwt')
  await note.press('w')
  await expect(note).toHaveValue('jkwtw')
  await expect(c.page.getByRole('dialog')).toHaveCount(0)
  await c.page.locator('.booking-update-banner .text-button').click()
  await expect(note).toHaveValue('jkwtw')
  await save(c.page, 'Follow-up completed by assignee')
  await expect(c.page.locator('.assignment-row')).toHaveCount(0)
  await b.page.getByRole('button', { name: /Assigned to me/ }).click()
  await b.page.getByLabel('View', { exact: true }).selectOption('from_me')
  await b.page.getByLabel('Status', { exact: true }).selectOption('done')
  await expect(b.page.locator('.assignment-row')).toContainText('Please check supplier mail')
  await b.page.locator('.notifications-menu summary').click()
  await expect(b.page.locator('.notification-list')).toContainText('completed')
  await b.page.locator('.notifications-menu summary').click()
  await a.page.getByRole('button', { name: 'Watching', exact: true }).click()
  const row = a.page.locator('.collaboration-list tbody tr').first()
  await expect(row).toContainText('CW 2154654-RDU-2609')
  await row.focus()
  await row.press('j')
  await row.press('k')
  await row.press('t')
  await expect(a.page.getByRole('dialog', { name: 'Booking reminders', exact: true })).toBeVisible()
  await a.page.keyboard.press('Escape')
  await expect(a.page.getByRole('dialog', { name: 'Booking reminders', exact: true })).toBeHidden()
  await row.focus()
  await expect(row).toBeFocused()
  await row.press('Enter')
  await expect(a.page.locator('.booking-summary-card')).toContainText('CW 2154654-RDU-2609')
  await row.focus()
  await expect(row).toBeFocused()
  await row.press('w')
  await expect(a.page.locator('.collaboration-list tbody tr')).toHaveCount(0)
  await a.page.keyboard.press('Control+k')
  const adminPalette = a.page.getByRole('dialog', { name: 'Command palette', exact: true })
  await expect(adminPalette).toContainText('Go to Admin')
  await expect(adminPalette).toContainText('Recent bookings')
  await a.page.keyboard.press('Escape')
  await b.page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(()=>b.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await b.page.locator('.my-bookings-card').screenshot({path:path.join(artifacts,'collaboration-mobile.png')})
  expect(errors).toEqual([])
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} catch (error) {
  let index = 0
  for (const context of browser.contexts())
    for (const page of context.pages()) {
      await page.screenshot({
        path: path.join(artifacts, `collaboration-failure-${index++}.png`),
        fullPage: true,
      })
      process.stderr.write(
        JSON.stringify({
          url: page.url(),
          card: await page
            .locator('.my-bookings-card')
            .innerText()
            .catch(() => ''),
          errors,
        }) + '\n',
      )
    }
  throw error
} finally {
  await browser.close()
}
