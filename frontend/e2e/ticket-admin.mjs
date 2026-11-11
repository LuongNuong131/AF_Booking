import { chromium, expect } from '@playwright/test'
import { mkdir, readFile } from 'node:fs/promises'
import path from 'node:path'
const output = process.env.BOOKING_E2E_ARTIFACTS, api = process.env.BOOKING_E2E_API_URL
if (!output || !api || !process.env.BOOKING_E2E_PASSWORD) throw new Error('Use the isolated browser test runner.')
await mkdir(output, { recursive: true })
const key = 'CW2154654-RDU-2609'
async function send(endpoint, token, body, method = 'POST') {
  const response = await fetch(api + endpoint, { method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) })
  if (!response.ok) throw new Error(`${endpoint}: ${response.status}`)
  return response.json()
}
const seed = await send('/auth/login', null, { username: 'agent', password: process.env.BOOKING_E2E_PASSWORD })
const contract = await send(`/bookings/${key}/work-tasks`, seed.access_token, { issue_type: 'contract', message: 'Please review the contract test evidence.', client_request_id: crypto.randomUUID() })
await send(`/bookings/${key}/work-tasks`, seed.access_token, { issue_type: 'cannot_send_rejection_letters', message: 'The rejection letter test needs follow-up.', client_request_id: crypto.randomUUID() })
const upload = await fetch(`${api}/work-tasks/${contract.id}/attachments?file_name=admin-test.png`, { method: 'POST', headers: { Authorization: `Bearer ${seed.access_token}`, 'Content-Type': 'image/png' }, body: await readFile('public/brand/af-logo.png') })
expect(upload.status).toBe(201)
const browser = await chromium.launch({ headless: true, ...(process.env.BOOKING_CHROMIUM_PATH ? { executablePath: process.env.BOOKING_CHROMIUM_PATH } : {}) })
const errors = [], contexts = []
async function login(role) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' })
  contexts.push(context)
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await expect(async () => { await page.goto('http://localhost:5173/login'); await expect(page.getByLabel('Username', { exact: true })).toBeVisible() }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill(role)
  await page.getByLabel('Password', { exact: true }).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.locator('.topbar')).toBeVisible()
  return page
}
async function navigate(page, target) { await page.evaluate(async target => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push(target) }, target) }
try {
  const page = await login('admin')
  await navigate(page, '/tickets')
  await page.getByRole('link', { name: 'Ticket management', exact: true }).click()
  await expect(page).toHaveURL(/\/admin\/tickets$/)
  await expect(page.locator('.admin-tabs').getByRole('link', { name: 'Ticket management', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Ticket management', exact: true })).toBeVisible()
  await expect(page.getByLabel('Ticket status', { exact: true })).toHaveValue('all')
  const card = page.locator('.ticket-card').filter({ hasText: 'AF_Non-standard process_Contract issue' })
  await card.getByRole('button', { name: 'Open ticket', exact: true }).click()
  await expect(page.locator('.ticket-detail img')).toBeVisible()
  await card.getByRole('button', { name: 'Edit ticket', exact: true }).click()
  let dialog = page.getByRole('dialog')
  const title = `Admin test contract - ${key}`
  await dialog.getByLabel('Title', { exact: true }).fill(title)
  await dialog.getByLabel('Content (English, required)', { exact: true }).fill('Corrected contract test data for the administrator.')
  await dialog.getByLabel('Ticket status', { exact: true }).selectOption('handled')
  await dialog.getByLabel('Customer follow-up / handling result (optional)', { exact: true }).fill('Admin test completed')
  await dialog.getByRole('button', { name: 'Save changes', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  const edited = page.locator('.ticket-card').filter({ hasText: title })
  await expect(edited.locator('.ticket-status')).toHaveText('Handled')
  await expect(page.locator('.ticket-card')).toHaveCount(2)
  await edited.getByRole('button', { name: 'Open ticket', exact: true }).click()
  await expect(page.locator('.ticket-detail')).toContainText('Corrected contract test data')
  await expect(page.locator('.ticket-detail img')).toHaveCount(1)
  const token = await page.evaluate(() => localStorage.getItem('booking.access_token'))
  const endpoint = `/work-tasks/${contract.id}`
  await edited.getByRole('button', { name: 'Edit ticket', exact: true }).click()
  dialog = page.getByRole('dialog')
  const latest = await send(endpoint, token, null, 'GET')
  await send(endpoint, token, { title: latest.title, message: 'Concurrent correction retained for the test.', issue_type: latest.issue_type, status: latest.status, handling_note: latest.handling_note, expected_token: latest.edit_token }, 'PATCH')
  await dialog.getByLabel('Content (English, required)', { exact: true }).fill('Attempting an edit from an older version.')
  await dialog.getByRole('button', { name: 'Save changes', exact: true }).click()
  await expect(dialog).toContainText('This ticket changed while you were editing.')
  await expect(dialog.getByLabel('Content (English, required)', { exact: true })).toHaveValue('Attempting an edit from an older version.')
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  expect((await send(endpoint, token, null, 'GET')).message).toBe('Concurrent correction retained for the test.')
  await page.screenshot({ path: path.join(output, 'admin-ticket-management.png'), fullPage: true })
  await edited.getByRole('button', { name: 'Delete', exact: true }).click()
  dialog = page.getByRole('dialog')
  await dialog.getByLabel('Reason for deletion', { exact: true }).fill('Remove isolated test ticket')
  await dialog.getByRole('button', { name: 'Move to recycle bin', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(edited).toHaveCount(0)
  await navigate(page, '/admin/trash')
  const trash = page.locator('tbody tr').filter({ hasText: 'Concurrent correction retained for the test.' })
  await expect(trash).toBeVisible()
  await trash.getByRole('button', { name: 'Restore', exact: true }).click()
  await expect(trash).toHaveCount(0)
  await navigate(page, '/admin/tickets')
  await expect(page.locator('.ticket-card')).toHaveCount(2)
  await page.locator('.ticket-card').filter({ hasText: title }).getByRole('button', { name: 'Open ticket', exact: true }).click()
  await expect(page.locator('.ticket-detail')).toContainText('Concurrent correction retained for the test.')
  await expect(page.locator('.ticket-detail img')).toHaveCount(1)
  await page.setViewportSize({ width: 375, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(376)
  for (const role of ['agent', 'qc']) {
    const other = await login(role)
    await navigate(other, '/admin/tickets')
    await expect(other).toHaveURL('http://localhost:5173/')
    await expect(other.locator('.admin-tickets-view')).toHaveCount(0)
    await navigate(other, '/tickets')
    await expect(other.getByRole('link', { name: 'Ticket management', exact: true })).toHaveCount(0)
    await expect(other.getByRole('button', { name: 'Edit ticket', exact: true })).toHaveCount(0)
  }
  expect(errors).toEqual([])
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} catch (error) {
  let index = 0
  for (const context of contexts) for (const page of context.pages()) {
    await page.screenshot({ path: path.join(output, `ticket-admin-failed-${++index}.png`), fullPage: true }).catch(() => undefined)
    process.stderr.write(JSON.stringify({ url: page.url(), body: await page.locator('body').innerText(), errors }) + '\n')
  }
  throw error
} finally { await Promise.all(contexts.map(context => context.close())); await browser.close() }
