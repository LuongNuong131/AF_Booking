// Only disposable database/accounts supplied by tests/test_frontend_database.py.
import { chromium, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
const api = process.env.BOOKING_E2E_API_URL
const output = process.env.BOOKING_E2E_ARTIFACTS
const workbook = process.env.BOOKING_E2E_ASSIGNMENT_WORKBOOK
if (!api || !output || !workbook || !process.env.BOOKING_E2E_PASSWORD) throw new Error('Disposable browser fixture required')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: process.env.BOOKING_CHROMIUM_PATH || '/usr/bin/chromium' })
const errors = []
async function navigate(page, target) {
  await page.evaluate(async target => {
    await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push(target)
  }, target)
}
async function login(username) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' })
  const page = await context.newPage()
  page.on('pageerror', e => errors.push(e.message))
  await expect(async () => {
    await page.goto('http://localhost:5173/login')
    await expect(page.getByLabel('Username', { exact: true })).toBeVisible()
  }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.locator('.topbar')).toBeVisible()
  return { page, context }
}
try {
  const admin = await login('admin')
  await navigate(admin.page, '/admin/import')
  const importer = admin.page.locator('.assignment-import')
  await importer.locator('input[type=file]').setInputFiles({ name: 'Booking_Merged_Agents.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from(workbook, 'base64') })
  await importer.getByText('Map Excel agents to existing usernames', { exact: true }).click()
  await importer.getByLabel('Luong', { exact: true }).selectOption('agent')
  await importer.getByLabel('Tran', { exact: true }).selectOption('other')
  await importer.getByRole('button', { name: 'Preview import', exact: true }).click()
  await expect(importer.locator('.assignment-preview')).toContainText('4 unique station bookings')
  await importer.getByRole('button', { name: 'Import these bookings', exact: true }).click()
  await expect(importer).toContainText('Assignments imported.')
  await navigate(admin.page, '/')
  const panel = admin.page.locator('.folder-assignments')
  await panel.getByLabel('Show', { exact: true }).selectOption('all')
  await expect(panel.locator('.assignment-card')).toHaveCount(3)
  await admin.page.screenshot({ path: path.join(output, 'assignments-all-desktop.png'), fullPage: true })
  const agent = await login('agent')
  const mine = agent.page.locator('.folder-assignments')
  await expect(mine.locator('.assignment-card')).toHaveCount(1)
  await expect(mine.locator('.assignment-card')).toContainText('RDU · HT')
  await mine.locator('.assignment-open').click()
  await expect(mine.locator('.month-row')).toHaveCount(2)
  await mine.getByRole('button', { name: 'Edit classification', exact: true }).click()
  const editor = mine.locator('.assignment-editor')
  await editor.getByLabel('Type', { exact: true }).selectOption('transportation')
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(editor).toHaveCount(0)
  await expect(mine.locator('.assignment-card')).toContainText('RDU · GT')
  await mine.locator('.month-row').filter({ hasText: '2610' }).click()
  await expect(agent.page.locator('.booking-summary-card')).toContainText('CW 2154654-RDU-2610')
  // Another active user can open and work in the assigned folder.
  const other = await login('other')
  const others = other.page.locator('.folder-assignments')
  await others.getByLabel('Show', { exact: true }).selectOption('all')
  await expect(others.locator('.assignment-card')).toHaveCount(3)
  await others.locator('.assignment-card').filter({ hasText: 'RDU' }).locator('.assignment-open').click()
  await expect(others.locator('.month-row')).toHaveCount(2)
  await others.locator('.month-row').filter({ hasText: '2610' }).click()
  await expect(other.page.locator('.booking-summary-card')).toContainText('CW 2154654-RDU-2610')
  for (const width of [320, 375, 768, 1440]) {
    await agent.page.setViewportSize({ width, height: 1000 })
    await expect(mine).toBeVisible()
    await agent.page.evaluate(() => window.scrollTo(0, 0))
    const overflow = await agent.page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)
    if (overflow) {
      await agent.page.screenshot({ path: path.join(output, 'assignments-overflow.png'), fullPage: true })
      console.warn(JSON.stringify(await agent.page.evaluate(() => [...document.querySelectorAll('*')].filter(e => e.getBoundingClientRect().right > innerWidth + 1).map(e => ({ tag: e.tagName, cls: e.className, right: e.getBoundingClientRect().right })).slice(0, 25))))
    }
    expect(overflow, `overflow at ${width}`).toBe(false)
    await agent.page.screenshot({ path: path.join(output, `assignments-${width}.png`), fullPage: true })
  }
  expect(errors).toEqual([])
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally { await browser.close() }
