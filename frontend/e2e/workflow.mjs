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
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'http://localhost:5173' })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await expect(async () => { await page.goto('http://localhost:5173/login'); await expect(page.locator('input[type=password]')).toBeVisible() }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.locator('.topbar')).toBeVisible()
  return page
}
async function booking(page, key = KEY) {
  await page.getByRole('link', { name: 'Home', exact: true }).click()
  await page.getByLabel('Smart search', { exact: true }).fill(key)
  await page.getByLabel('Smart search', { exact: true }).press('Enter')
  await expect(page.locator('.booking-summary-card')).toContainText(key.replace('CW', 'CW '))
}
try {
  const agent = await login('agent'), qc = await login('qc')
  await qc.getByRole('link', { name: 'Tickets', exact: true }).click()
  await expect(qc.getByRole('heading', { name: 'QC ticket desk', exact: true })).toBeVisible()
  await agent.getByRole('link', { name: 'Reports', exact: true }).click()
  await expect(agent.getByRole('heading', { name: 'My work report', exact: true })).toBeVisible()
  await expect(agent.locator('.report-kpis article').first()).toContainText('1')
  const reportDownload = agent.waitForEvent('download')
  await agent.getByRole('button', { name: 'Export Excel', exact: true }).click()
  expect((await reportDownload).suggestedFilename()).toContain('af-booking-mine-')
  await agent.screenshot({ path: path.join(output, 'my-daily-report.png'), fullPage: true })
  await booking(agent)
  const tickets = agent.locator('.booking-ticket-panel')
  await tickets.locator('summary').first().click()
  await tickets.getByLabel('Content (English, required)', { exact: true }).fill('Customer reports incorrect room details. Please confirm with the customer.')
  const logo = await readFile('public/brand/af-logo.png')
  const ticketImages = tickets.locator('.staged-images')
  await ticketImages.locator('summary').click()
  await ticketImages.locator('input[type=file]').setInputFiles([
    { name: 'contract.png', mimeType: 'image/png', buffer: logo },
    { name: 'contract-detail.png', mimeType: 'image/png', buffer: Buffer.concat([logo, Buffer.from([1])]) },
  ])
  await expect(ticketImages.locator('img')).toHaveCount(2)
  await tickets.getByRole('button', { name: 'Create ticket', exact: true }).click()
  await expect(tickets).toContainText('Ticket created. QC has been notified.')
  await expect(qc.locator('.ticket-card')).toContainText('incorrect room details')
  await expect(qc.locator('.notification-badge')).toHaveText('1')
  await qc.getByRole('button', { name: 'Open ticket', exact: true }).click()
  await expect(qc.locator('.ticket-detail h3').first()).toHaveText(`AF_Non-standard process_Contract issue - ${KEY}`)
  await expect(qc.locator('.ticket-detail img')).toHaveCount(2)
  await qc.bringToFront()
  await qc.locator('.ticket-detail').getByRole('button', { name: 'Copy title + content', exact: true }).click()
  await expect(qc.locator('.ticket-copy')).toContainText('Copied.')
  expect(await qc.evaluate(() => navigator.clipboard.readText())).toBe(`AF_Non-standard process_Contract issue - ${KEY}\n\nCustomer reports incorrect room details. Please confirm with the customer.`)
  await qc.locator('.ticket-detail').getByLabel('Customer follow-up / handling result (optional)', { exact: true }).fill('Contacted the customer and confirmed the correct room details.')
  await qc.getByRole('button', { name: 'Mark as handled', exact: true }).click()
  await expect(qc.locator('.ticket-card')).toHaveCount(0)
  await qc.getByLabel('Ticket status', { exact: true }).selectOption('handled')
  await qc.getByRole('button', { name: 'Apply filters', exact: true }).click()
  await qc.getByRole('button', { name: 'Open ticket', exact: true }).click()
  await expect(qc.locator('.ticket-handled')).toContainText('Contacted the customer')
  const ticketDownload = qc.waitForEvent('download')
  await qc.getByRole('button', { name: 'Download Excel', exact: true }).click()
  expect((await ticketDownload).suggestedFilename()).toContain('qc-tickets')
  await qc.screenshot({ path: path.join(output, 'qc-tickets.png'), fullPage: true })
  await agent.getByRole('link', { name: 'Tickets', exact: true }).click()
  await expect(agent.getByRole('button', { name: 'Mark as handled', exact: true })).toHaveCount(0)
  await agent.getByLabel('Ticket status', { exact: true }).selectOption('handled')
  await agent.getByRole('button', { name: 'Apply filters', exact: true }).click()
  await agent.getByRole('button', { name: 'Open ticket', exact: true }).click()
  await expect(agent.locator('.ticket-handled')).toContainText('Quality Control')
  await booking(agent)
  // Images are selected in the note composer and survive an upload failure + reload.
  const noteForm = agent.locator('.note-form'), staged = noteForm.locator('.staged-images')
  await noteForm.getByRole('button', { name: /^Bundle/ }).click()
  await noteForm.getByLabel('Note', { exact: true }).fill('Evidence selected before saving this update.')
  await staged.locator('summary').click()
  await staged.locator('input[type=file]').setInputFiles([
    { name: 'note-example.png', mimeType: 'image/png', buffer: logo },
    { name: 'note-detail.png', mimeType: 'image/png', buffer: Buffer.concat([logo, Buffer.from([2])]) },
  ])
  await expect(staged.locator('img')).toHaveCount(2)
  let failUpload = true, notePosts = 0
  agent.on('request', request => { if (request.method() === 'POST' && /\/bookings\/[^/]+\/notes$/.test(new URL(request.url()).pathname)) notePosts++ })
  await agent.route('**/notes/*/attachments?*', route => failUpload
    ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 'SERVICE_BUSY', message: 'Retry image upload' }) })
    : route.continue())
  await noteForm.locator('.save-note').click()
  await expect(agent.locator('.outbox-panel')).toContainText('Note saved.')
  failUpload = false
  await agent.reload()
  await booking(agent)
  await expect(agent.locator('.outbox-panel')).toHaveCount(0)
  const restored = agent.locator('.note-images').first()
  await expect(restored.locator('summary')).toContainText('2')
  await restored.locator('summary').click()
  await expect(restored.locator('img')).toHaveCount(2)
  await expect.poll(() => restored.locator('img').first().evaluate(image => image.naturalWidth)).toBeGreaterThan(0)
  expect(notePosts).toBe(1)
  await agent.screenshot({ path: path.join(output, 'note-images.png'), fullPage: true })

  // Vietnamese translation is optional; review/paste works without a provider key.
  const compose = agent.locator('.booking-ticket-panel')
  await compose.locator('summary').first().click()
  await compose.getByLabel('Issue suggestion', { exact: true }).selectOption('cannot_send_rejection_letters')
  await compose.getByLabel('Content (English, required)', { exact: true }).fill('Không thể gửi thư từ chối')
  await expect(compose.getByRole('button', { name: 'Create ticket', exact: true })).toBeDisabled()
  await compose.locator('.ticket-translation summary').click()
  await compose.getByLabel('Describe the issue in Vietnamese', { exact: true }).fill('Không thể gửi thư từ chối trên TIM Tool')
  await expect(compose.getByRole('link', { name: 'Open Google Translate', exact: true })).toHaveAttribute('href', /sl=vi&tl=en/)
  await compose.getByLabel('Review the English translation, or paste it from Google Translate', { exact: true }).fill('Cannot send the rejection letter on TIM Tool.')
  await compose.getByRole('button', { name: 'Use this English content', exact: true }).click()
  await compose.getByRole('button', { name: 'Create ticket', exact: true }).click()
  await expect(compose).toContainText('Ticket created. QC has been notified.')
  const secondKey = 'CW9997777-YUL-2610'
  await booking(agent, secondKey)
  const secondCompose = agent.locator('.booking-ticket-panel')
  await secondCompose.locator('summary').first().click()
  await secondCompose.getByLabel('Issue suggestion', { exact: true }).selectOption('cannot_send_rejection_letters')
  await secondCompose.getByLabel('Content (English, required)', { exact: true }).fill('The rejection letter was sent manually via Billing Email.')
  await secondCompose.getByRole('button', { name: 'Create ticket', exact: true }).click()
  await expect(secondCompose).toContainText('Ticket created. QC has been notified.')
  await qc.getByLabel('Ticket status', { exact: true }).selectOption('pending')
  await qc.getByRole('button', { name: 'Apply filters', exact: true }).click()
  await expect(qc.locator('.ticket-card')).toHaveCount(2)
  for (const checkbox of await qc.locator('.ticket-select input').all()) await checkbox.check()
  await qc.getByRole('button', { name: 'Combine for copying', exact: true }).click()
  await expect(qc.locator('.ticket-bundle h3')).toHaveText('AF_System Issues_Cannot send rejection letters')
  await expect(qc.locator('.ticket-bundle .ticket-message')).toHaveText(
    'Please check these invoice which cannot send the rejection letter on TIM Tool - we had to send manually the rejection letter via Billing Email section, and force it from the Parking tab to Rejection tab\n\n' + secondKey + '\n' + KEY,
  )
  await qc.bringToFront()
  await qc.locator('.ticket-bundle').getByRole('button', { name: 'Copy content', exact: true }).click()
  await expect(qc.locator('.ticket-bundle .ticket-copy')).toContainText('Copied.')
  expect(await qc.evaluate(() => navigator.clipboard.readText())).toBe(await qc.locator('.ticket-bundle .ticket-message').innerText())
  await qc.screenshot({ path: path.join(output, 'qc-combined-ticket.png'), fullPage: true })
  for (const page of [agent, qc]) {
    await page.setViewportSize({ width: 375, height: 844 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(376)
  }
  await agent.goto('http://localhost:5173/reports')
  await expect(agent.getByRole('heading', { name: 'My work report', exact: true })).toBeVisible()
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
