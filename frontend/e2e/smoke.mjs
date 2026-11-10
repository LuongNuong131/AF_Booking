// Driven by tests/test_frontend_database.py: real backend, no mocked application APIs.
import { chromium, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { createInterface } from 'node:readline'
import path from 'node:path'

const input = createInterface({ input: process.stdin })
let acknowledge
input.on('line', (line) => {
  if (JSON.parse(line).ok) {
    acknowledge?.()
    acknowledge = null
  }
})
async function command(action) {
  const complete = new Promise((resolve) => {
    acknowledge = resolve
  })
  process.stdout.write(JSON.stringify({ action }) + '\n')
  await complete
}
const artifacts = process.env.BOOKING_E2E_ARTIFACTS
await mkdir(artifacts, { recursive: true })
const browser = await chromium.launch({
  headless: true,
  ...(process.env.BOOKING_CHROMIUM_PATH
    ? { executablePath: process.env.BOOKING_CHROMIUM_PATH }
    : {}),
})
const pageErrors = []
async function context(viewport = { width: 1440, height: 960 }) {
  const ctx = await browser.newContext({ viewport, reducedMotion: 'reduce', colorScheme: 'light' })
  ctx.on('page', (page) => {
    page.on('pageerror', (error) => {
      pageErrors.push(error.name)
    })
  })
  return ctx
}
async function login(page, username, destination = '/') {
  await page.goto('http://localhost:5173' + destination)
  await page.getByRole('textbox', { name: 'Username', exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible()
}
try {
  const primary = await context(),
    page = await primary.newPage()
  // Wait for the owned Vite process without any production warmup endpoint.
  let loaded = false
  for (let i = 0; i < 50; i++) {
    try {
      await page.goto('http://localhost:5173/login')
      loaded = true
      break
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
  }
  expect(loaded).toBe(true)
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(artifacts, 'login-light.png'), fullPage: true })
  // Wrong-password errors stay inline, fields remain editable and focusable.
  await page.getByRole('textbox', { name: 'Username', exact: true }).fill('agent')
  await page.getByLabel('Password', { exact: true }).fill('deliberately-wrong-test-password')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.locator('.inline-error')).toBeVisible()
  await expect(page.getByLabel('Password', { exact: true })).toBeEditable()
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Admin', exact: true })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Reports', exact: true })).toBeVisible()
  await page.goto('http://localhost:5173/admin/users')
  await expect(page).toHaveURL('http://localhost:5173/')
  await page.getByRole('link', { name: 'Profile', exact: true }).click()
  await page.getByRole('combobox', { name: 'Appearance', exact: true }).selectOption('dark')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(artifacts, 'profile-dark.png'), fullPage: true })
  await page.getByRole('button', { name: 'Show keyboard shortcuts', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await command('takeover')
  await expect(page.locator('.notification-badge')).toHaveText('1')
  await page.getByLabel('Open notifications', { exact: true }).click()
  await expect(page.locator('.notification-list')).toContainText(
    'Other added a note to booking CW 2154654-RDU-2609',
  )
  await page.locator('.notification-list button').first().click()
  await expect(page).toHaveURL('http://localhost:5173/summary/CW2154654-RDU-2609')
  await expect(page.locator('.notification-badge')).toHaveCount(0)
  await page.goto('http://localhost:5173/summary/CW%202154654-rdu-2609')
  await expect(page).toHaveURL('http://localhost:5173/summary/CW2154654-RDU-2609')
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible()
  let notificationReads = 0
  page.on('request', (request) => {
    if (request.method() === 'GET' && new URL(request.url()).pathname === '/api/v1/notifications')
      notificationReads++
  })
  await command('stop_backend')
  await expect(page.getByLabel('Realtime connection: Reconnecting…', { exact: true })).toBeVisible()
  await command('start_backend')
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible({
    timeout: 20000,
  })
  await expect.poll(() => notificationReads).toBeGreaterThan(0)
  await expect(page).toHaveURL('http://localhost:5173/summary/CW2154654-RDU-2609')
  const replacement = await context(),
    second = await replacement.newPage()
  await login(second, 'agent')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByRole('alert')).toContainText(
    'Your account was signed in on another device.',
  )
  expect(await page.evaluate(() => sessionStorage.getItem('booking.access_token'))).toBeNull()
  await replacement.close()
  await primary.close()
  const qc = await context(),
    qcPage = await qc.newPage()
  await login(qcPage, 'qc', '/reports')
  await expect(qcPage).toHaveURL('http://localhost:5173/reports')
  await expect(qcPage.getByRole('link', { name: 'Reports', exact: true })).toBeVisible()
  await expect(qcPage.getByRole('link', { name: 'Admin', exact: true })).toHaveCount(0)
  await qc.close()
  const admin = await context(),
    adminPage = await admin.newPage()
  await login(adminPage, 'admin', '/admin/users')
  await expect(adminPage.getByRole('link', { name: 'Admin', exact: true })).toBeVisible()
  await expect(adminPage).toHaveURL('http://localhost:5173/admin/users')
  await adminPage.setViewportSize({ width: 390, height: 844 })
  await adminPage.getByRole('button', { name: 'Toggle navigation' }).click()
  await expect(adminPage.getByRole('link', { name: 'Summary', exact: true })).toBeVisible()
  await adminPage.getByRole('link', { name: 'Summary', exact: true }).click()
  await expect(adminPage.getByRole('heading', { name: 'Summary', exact: true })).toBeVisible()
  expect(await adminPage.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
    true,
  )
  await adminPage.getByLabel('Open notifications', { exact: true }).click()
  const box = await adminPage.locator('.notifications-popover').boundingBox()
  expect(box.x).toBeGreaterThanOrEqual(0)
  expect(box.x + box.width).toBeLessThanOrEqual(390)
  await adminPage.screenshot({
    path: path.join(artifacts, 'mobile-notifications.png'),
    fullPage: true,
  })
  await adminPage.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(adminPage).toHaveURL('http://localhost:5173/login')
  expect(await adminPage.evaluate(() => sessionStorage.getItem('booking.access_token'))).toBeNull()
  expect(pageErrors).toEqual([])
  await admin.close()
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally {
  input.close()
  await browser.close()
}
