// Actual task APIs and scheduler events, with only an owned DB clock advance via the test harness.
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
  const p = new Promise((resolve) => {
    acknowledge = resolve
  })
  process.stdout.write(JSON.stringify({ action }) + '\n')
  await p
}
const browser = await chromium.launch({
  headless: true,
  ...(process.env.BOOKING_CHROMIUM_PATH
    ? { executablePath: process.env.BOOKING_CHROMIUM_PATH }
    : {}),
})
const KEY = 'CW2154654-RDU-2609',
  errors = []
async function login() {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 1050 },
    reducedMotion: 'reduce',
    colorScheme: 'light',
  })
  const page = await ctx.newPage()
  page.on('pageerror', (e) => errors.push(e.name))
  await expect(async () => {
    await page.goto('http://localhost:5173')
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill('agent')
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible()
  return { ctx, page }
}
async function openTask(page) {
  await page.locator('.booking-summary-card .task-button').click()
  await expect(page.getByRole('dialog', { name: 'Booking reminders' })).toBeVisible()
}
async function createTask(page, text) {
  await openTask(page)
  await page.getByLabel('Reminder message', { exact: true }).fill(text)
  const response = page.waitForResponse(
    (r) =>
      r.request().method() === 'POST' &&
      new URL(r.url()).pathname === `/api/v1/bookings/${KEY}/tasks`,
  )
  await page.getByLabel('Reminder message', { exact: true }).press('Enter')
  const reply = await response
  expect(reply.status()).toBe(200)
  const payload = reply.request().postDataJSON()
  expect(payload).toHaveProperty('remind_date')
  expect(payload).toHaveProperty('remind_time')
  expect(payload).not.toHaveProperty('remind_at')
  await expect(page.getByRole('dialog', { name: 'Booking reminders' })).toHaveCount(0)
}
try {
  let { ctx, page } = await login()
  await page.getByLabel('Smart search', { exact: true }).fill(KEY)
  await page.getByLabel('Smart search', { exact: true }).press('Enter')
  await expect(page.locator('.booking-summary-card')).toContainText('Example Hotel')
  await page.getByLabel('Smart search', { exact: true }).press('Alt+t')
  await expect(page.getByRole('dialog', { name: 'Booking reminders' })).toBeVisible()
  await expect(page.locator('.task-confirmation')).toContainText('Reminder on:')
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await createTask(page, 'Check mail for the overnight crew')
  await expect(page.locator('.booking-summary-card .task-count')).toHaveText('1')
  await page.getByRole('button', { name: 'Task (0)', exact: true }).click()
  await expect(page.locator('.task-row')).toHaveCount(1)
  await command('task_due')
  await expect(page.locator('.task-reminder-toast')).toContainText(
    'Task due: check the mail for booking CW 2154654-RDU-2609',
  )
  await expect(page.getByRole('button', { name: 'Task (1)', exact: true })).toBeVisible()
  await expect(page).toHaveTitle(/\(1\) Tasks due/)
  await expect(page.locator('.notification-badge')).toHaveText('1')
  await page.screenshot({ path: path.join(artifacts, 'tasks-due.png'), fullPage: true })
  await page.locator('.task-reminder-toast summary').click()
  const snoozing = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith('/snooze'))
  await page
    .locator('.task-reminder-toast')
    .getByRole('button', { name: 'Tomorrow', exact: true })
    .click()
  expect((await snoozing).status()).toBe(200)
  await expect(page.locator('.task-reminder-toast')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Task (0)', exact: true })).toBeVisible()
  await command('task_due')
  await expect(page.locator('.task-reminder-toast')).toHaveCount(1)
  await ctx.close()
  ;({ ctx, page } = await login())
  await expect(page.getByRole('dialog')).toContainText('You have 1 task(s) due')
  await page.getByRole('dialog').getByRole('button', { name: 'Open booking', exact: true }).click()
  await expect(page.locator('.booking-summary-card')).toContainText('CW 2154654-RDU-2609')
  await page.getByRole('button', { name: 'Task (1)', exact: true }).click()
  await expect(page.locator('.task-row')).toHaveCount(1)
  const completing = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith('/complete'))
  await page.locator('.task-row').getByRole('button', { name: 'Done', exact: true }).click()
  expect((await completing).status()).toBe(200)
  await expect(page.getByRole('button', { name: 'Task (0)', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Add a note', exact: true }).click()
  await expect(page.getByLabel('Note', { exact: true })).toBeFocused()
  await page.locator('.task-list-toolbar select').selectOption('done')
  await expect(page.locator('.task-row')).toHaveCount(1)
  await page.getByRole('link', { name: 'Profile', exact: true }).click()
  await page.getByLabel('Default reminder time', { exact: true }).fill('10:45')
  await page.getByLabel('Skip weekends by default', { exact: true }).uncheck()
  await page.getByRole('button', { name: 'Save preferences', exact: true }).click()
  await expect(page.getByText('Reminder preferences saved.', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('Default reminder time', { exact: true })).toHaveValue('10:45')
  await expect(page.getByLabel('Skip weekends by default', { exact: true })).not.toBeChecked()
  await page.getByRole('link', { name: 'Home', exact: true }).click()
  await page.getByLabel('Smart search', { exact: true }).fill(KEY)
  await page.getByLabel('Smart search', { exact: true }).press('Enter')
  await expect(page.locator('.booking-summary-card')).toContainText('Example Hotel')
  for (let i = 0; i < 5; i++) await createTask(page, `Check supplier update ${i + 1}`)
  await openTask(page)
  await expect(page.getByLabel('Reminder time', { exact: true })).toHaveValue('10:45')
  await expect(page.locator('.booking-pending-tasks h3')).toHaveText('Pending reminders (5/5)')
  const limited = page.waitForResponse(
    (r) =>
      r.request().method() === 'POST' &&
      new URL(r.url()).pathname === `/api/v1/bookings/${KEY}/tasks`,
  )
  await page.getByRole('button', { name: 'Create task', exact: true }).click()
  expect((await limited).status()).toBe(422)
  await expect(page.locator('.task-form .inline-error')).toContainText('up to 5 pending reminders')
  await page
    .locator('.booking-pending-tasks article')
    .first()
    .getByRole('button', { name: 'Edit', exact: true })
    .click()
  await page.getByLabel('Reminder message', { exact: true }).fill('Edited reminder text')
  const edited = page.waitForResponse(
    (r) => r.request().method() === 'PATCH' && new URL(r.url()).pathname.includes('/tasks/'),
  )
  await page.getByRole('button', { name: 'Save changes', exact: true }).click()
  expect((await edited).status()).toBe(200)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await openTask(page)
  await expect(page.locator('.booking-pending-tasks')).toContainText('Edited reminder text')
  await page
    .locator('.booking-pending-tasks article')
    .first()
    .getByRole('button', { name: 'Cancel task', exact: true })
    .click()
  await expect(page.locator('.booking-pending-tasks h3')).toHaveText('Pending reminders (4/5)')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true)
  await page.screenshot({ path: path.join(artifacts, 'tasks-mobile.png'), fullPage: true })
  expect(errors).toEqual([])
  await ctx.close()
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally {
  input.close()
  await browser.close()
}
