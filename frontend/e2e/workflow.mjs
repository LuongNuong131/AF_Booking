import { chromium, expect } from '@playwright/test'
import { mkdir, readFile } from 'node:fs/promises'
import path from 'node:path'
const output = process.env.BOOKING_E2E_ARTIFACTS
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.env.BOOKING_CHROMIUM_PATH ? { executablePath: process.env.BOOKING_CHROMIUM_PATH } : {}) })
const errors = [], contexts = [], KEY = 'CW2154654-RDU-2609'
async function login(username) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' })
  contexts.push(context)
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await expect(async () => { await page.goto('http://localhost:5173/login'); await expect(page.locator('input[type=password]')).toBeVisible() }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.locator('.topbar')).toBeVisible()
  return page
}
async function booking(page) {
  await page.getByRole('link', { name: 'Home', exact: true }).click()
  await page.getByLabel('Smart search', { exact: true }).fill(KEY)
  await page.getByLabel('Smart search', { exact: true }).press('Enter')
  await expect(page.locator('.booking-summary-card')).toContainText('CW 2154654-RDU-2609')
}
try {
  const agent = await login('agent'), qc = await login('qc')
  await qc.getByRole('link', { name: 'Tickets', exact: true }).click()
  await expect(qc.getByRole('heading', { name: 'QC ticket desk', exact: true })).toBeVisible()
  await agent.getByRole('link', { name: 'Reports', exact: true }).click()
  await expect(agent.getByRole('heading', { name: 'My daily report', exact: true })).toBeVisible()
  await expect(agent.locator('.report-metrics article').first()).toContainText('1')
  const reportDownload = agent.waitForEvent('download')
  await agent.getByRole('button', { name: 'Download Excel', exact: true }).click()
  expect((await reportDownload).suggestedFilename()).toContain('my-daily-report')
  await agent.screenshot({ path: path.join(output, 'my-daily-report.png'), fullPage: true })
  await booking(agent)
  const tickets = agent.locator('.booking-ticket-panel')
  await tickets.locator('summary').click()
  await tickets.getByLabel('Issue and customer follow-up required', { exact: true }).fill('Customer reports incorrect room details. Please confirm with the customer.')
  await tickets.getByRole('button', { name: 'Create ticket', exact: true }).click()
  await expect(tickets).toContainText('Ticket created. QC has been notified.')
  await expect(qc.locator('.ticket-card')).toContainText('incorrect room details')
  await expect(qc.locator('.notification-badge')).toHaveText('1')
  await qc.locator('.ticket-card').getByLabel('Customer follow-up / handling result (optional)', { exact: true }).fill('Contacted the customer and confirmed the correct room details.')
  await qc.getByRole('button', { name: 'Mark as handled', exact: true }).click()
  await expect(qc.locator('.ticket-card')).toHaveCount(0)
  await qc.getByLabel('Ticket status', { exact: true }).selectOption('handled')
  await qc.getByRole('button', { name: 'Apply filters', exact: true }).click()
  await expect(qc.locator('.ticket-handled')).toContainText('Contacted the customer')
  const ticketDownload = qc.waitForEvent('download')
  await qc.getByRole('button', { name: 'Download Excel', exact: true }).click()
  expect((await ticketDownload).suggestedFilename()).toContain('qc-tickets')
  await qc.screenshot({ path: path.join(output, 'qc-tickets.png'), fullPage: true })
  await agent.getByRole('link', { name: 'Tickets', exact: true }).click()
  await expect(agent.getByRole('button', { name: 'Mark as handled', exact: true })).toHaveCount(0)
  await agent.getByLabel('Ticket status', { exact: true }).selectOption('handled')
  await agent.getByRole('button', { name: 'Apply filters', exact: true }).click()
  await expect(agent.locator('.ticket-handled')).toContainText('Quality Control')
  await booking(agent)
  const images = agent.locator('.note-images').first()
  await images.locator('summary').click()
  await images.locator('input[type=file]').setInputFiles({ name: 'booking-example.png', mimeType: 'image/png', buffer: await readFile('public/brand/af-logo.png') })
  await expect(images.locator('img')).toBeVisible()
  await expect.poll(() => images.locator('img').evaluate(image => image.naturalWidth)).toBeGreaterThan(0)
  await agent.screenshot({ path: path.join(output, 'note-images.png'), fullPage: true })
  await agent.reload()
  await booking(agent)
  await expect(agent.locator('.booking-summary-card')).toContainText('CW 2154654-RDU-2609')
  const restored = agent.locator('.note-images').first()
  await expect(restored.locator('summary')).toContainText('1')
  await restored.locator('summary').click()
  await expect(restored.locator('img')).toBeVisible()
  for (const page of [agent, qc]) {
    await page.setViewportSize({ width: 375, height: 844 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(376)
  }
  await agent.goto('http://localhost:5173/reports')
  await expect(agent.getByRole('heading', { name: 'My daily report', exact: true })).toBeVisible()
  await expect.poll(() => agent.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(376)
  expect(errors).toEqual([])
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} catch (error) {
  let index = 0
  for (const context of contexts) for (const page of context.pages()) {
    await page.screenshot({ path: path.join(output, `workflow-failed-${++index}.png`), fullPage: true }).catch(() => undefined)
    process.stderr.write(JSON.stringify({ url: page.url(), body: await page.locator('body').innerText(), errors }) + '\n')
  }
  throw error
} finally { await Promise.all(contexts.map(context => context.close())); await browser.close() }
