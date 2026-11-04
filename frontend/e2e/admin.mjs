import { chromium, expect } from '@playwright/test'
import { mkdir, readFile } from 'node:fs/promises'
import { randomUUID } from 'node:crypto'
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
  KEY = 'CW2154654-RDU-2609',
  DISPLAY = 'CW 2154654-RDU-2609'
async function login(username, password = process.env.BOOKING_E2E_PASSWORD) {
  const ctx = await browser.newContext({
      viewport: { width: 1440, height: 1050 },
      reducedMotion: 'reduce',
      colorScheme: 'light',
    }),
    page = await ctx.newPage()
  page.on('pageerror', (error) => errors.push(error.name + ': ' + error.message))
  await expect(async () => {
    await page.goto('http://localhost:5173')
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  })
    .toPass({ timeout: 15000 })
    .catch(async (error) => {
      await page.screenshot({ path: path.join(artifacts, 'login-failed.png') })
      console.error(errors)
      throw error
    })
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible()
  return { ctx, page }
}
async function go(page, url) {
  await page.goto('http://localhost:5173' + url)
  await expect(page.getByLabel('Realtime connection: Live', { exact: true })).toBeVisible({timeout:15000})
}

try {
  const a = await login('admin'),
    agent = await login('agent'),
    page = a.page
  await go(page, '/admin/users')
  await expect(page.getByRole('heading', { name: 'Admin', exact: true })).toBeVisible()
  const self = page
    .locator('.admin-table tbody tr')
    .filter({ has: page.getByText('admin', { exact: true }) })
  await expect(self.getByRole('button', { name: 'Disable', exact: true })).toBeDisabled()
  await self.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(page.getByRole('dialog').getByLabel('Role', { exact: true })).toBeDisabled()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Cancel request', exact: true })
    .click()
  const temporary = `Temp_${randomUUID()}!`
  await page.getByRole('button', { name: 'Create user', exact: true }).click()
  const create = page.getByRole('dialog', { name: 'Create user' })
  await create.getByLabel('Username', { exact: true }).fill('ui.agent')
  await create.getByLabel('Display name', { exact: true }).fill('UI Agent')
  await create.getByLabel('Temporary password', { exact: true }).fill(temporary)
  await create.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const row = page
    .locator('.admin-table tbody tr')
    .filter({ has: page.getByText('ui.agent', { exact: true }) })
  await expect(row).toContainText('UI Agent')
  await row.getByRole('button', { name: 'Edit', exact: true }).click()
  await page
    .getByRole('dialog')
    .getByLabel('Display name', { exact: true })
    .fill('Renamed UI Agent')
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(row).toContainText('Renamed UI Agent')
  const added = await login('ui.agent', temporary)
  await page.getByRole('button', { name: 'Apply filters', exact: true }).click()
  await expect(row.getByRole('button', { name: 'End session', exact: true })).toBeEnabled()
  await row.getByRole('button', { name: 'End session', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(added.page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  await added.ctx.close()
  await row.getByRole('button', { name: 'Disable', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(row).toContainText('Disabled')
  await row.getByRole('button', { name: 'Enable', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(row).toContainText('Active')
  await agent.page.getByLabel('Smart search', { exact: true }).fill(KEY)
  await expect(agent.page.locator('.booking-summary-card')).toContainText('Done')
  await page.getByRole('link', { name: 'Bookings & notes', exact: true }).click()
  await page.locator('.table-booking-link').filter({ hasText: DISPLAY }).click()
  const history = page.getByRole('dialog', {
    name: 'Complete note history',
    exact: true,
  })
  await expect(history.locator('.admin-note')).toHaveCount(2)
  await history
    .locator('.admin-note')
    .first()
    .getByRole('button', { name: 'Delete note', exact: true })
    .click()
  const deleting = page.getByRole('dialog', {
    name: 'Delete note',
    exact: true,
  })
  await expect(deleting.getByRole('button', { name: 'Confirm', exact: true })).toBeDisabled()
  await deleting
    .getByLabel('Reason for deletion', { exact: true })
    .fill('Incorrect completion record')
  await deleting.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(history).toContainText('Incorrect completion record')
  await expect(agent.page.locator('.booking-update-banner')).toBeVisible()
  await agent.page
    .locator('.booking-update-banner')
    .getByRole('button', { name: 'Refresh', exact: true })
    .click()
  await expect(agent.page.locator('.booking-summary-card')).toContainText('Bundle')
  await page.keyboard.press('Escape')
  await page.getByRole('link', { name: 'Trash', exact: true }).click()
  await expect(page.locator('.admin-note')).toHaveCount(1)
  await expect(page.locator('.admin-note')).toContainText('Incorrect completion record')
  await page
    .locator('.admin-note')
    .getByRole('button', { name: 'Restore note', exact: true })
    .click()
  await page
    .getByRole('dialog', { name: 'Restore note', exact: true })
    .getByRole('button', { name: 'Confirm', exact: true })
    .click()
  await expect(page.locator('.admin-note')).toHaveCount(0)
  await agent.page
    .locator('.booking-update-banner')
    .getByRole('button', { name: 'Refresh', exact: true })
    .click()
  await expect(agent.page.locator('.booking-summary-card')).toContainText('Done')
  await page.getByRole('link', { name: 'Statuses', exact: true }).click()
  await page
    .locator('.admin-table tbody tr')
    .filter({ hasText: 'BUNDLE' })
    .getByRole('button', { name: 'Edit', exact: true })
    .click()
  await page.getByRole('dialog').getByLabel('Label', { exact: true }).fill('Supplier review')
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(agent.page.locator('.status-options')).toContainText('Supplier review')
  await page.getByRole('button', { name: 'Create status', exact: true }).click()
  await page.getByRole('dialog').getByLabel('Code', { exact: true }).fill('FOLLOW_UP')
  await page.getByRole('dialog').getByLabel('Label', { exact: true }).fill('Follow up')
  await page.getByRole('dialog').getByLabel('Position', { exact: true }).fill('Awaiting reply')
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(agent.page.locator('.status-options')).toContainText('Follow up')
  await page.getByRole('link', { name: 'Audit log', exact: true }).click()
  await page.getByLabel('Action', { exact: true }).fill('note_deleted')
  await page.getByRole('button', { name: 'Apply filters', exact: true }).click()
  await expect(page.locator('.admin-table tbody tr')).toHaveCount(1)
  await page.locator('.admin-table details').click()
  await expect(page.locator('.audit-meta')).toContainText('Incorrect completion record')
  await page.screenshot({
    path: path.join(artifacts, 'admin-audit.png'),
    fullPage: true,
  })
  await page.getByRole('link', { name: 'Suppliers & Stations', exact: true }).click()
  await page.locator('.folder-card').click()
  const supplier = page.getByRole('dialog', {
    name: 'Supplier folder',
    exact: true,
  })
  await supplier.getByRole('button', { name: 'Edit supplier', exact: true }).click()
  await supplier.getByLabel('Supplier name', { exact: true }).fill('Updated Crew Hotel')
  await supplier.getByRole('button', { name: 'Save supplier', exact: true }).click()
  await expect(supplier).toContainText('Updated Crew Hotel')
  await supplier.locator('.el-dialog__headerbtn').click()
  await page.getByRole('button', { name: 'Stations', exact: true }).click()
  await page
    .locator('.admin-table tbody tr')
    .getByRole('button', { name: 'Edit', exact: true })
    .click()
  await page.getByRole('dialog').getByLabel('Label', { exact: true }).fill('Raleigh crew station')
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.locator('.admin-table')).toContainText('Raleigh crew station')
  const qc = await login('qc')
  await go(qc.page, '/reports')
  await expect(qc.page.locator('.reports-view > .report-metrics')).toContainText('Notes')
  await expect(qc.page.locator('.report-charts canvas')).toHaveCount(2)
  await qc.page.getByLabel('Format', { exact: true }).selectOption('csv')
  const download = qc.page.waitForEvent('download')
  await qc.page.getByRole('button', { name: 'Download', exact: true }).click()
  const file = await download,
    exportPath = path.join(artifacts, 'daily-record.csv')
  await file.saveAs(exportPath)
  const content = await readFile(exportPath, 'utf8')
  expect(
    content.startsWith('\ufeffDate,Agent,Booking,Supplier,Station,Type,Status,Position,Note'),
  ).toBe(true)
  expect(content.includes(DISPLAY)).toBe(true)
  expect(content.includes("'=1+1")).toBe(true)
  await qc.page.screenshot({
    path: path.join(artifacts, 'reports.png'),
    fullPage: true,
  })
  await go(qc.page, '/admin/users')
  await expect(qc.page).toHaveURL('http://localhost:5173/')
  await go(qc.page, '/profile')
  await qc.page.locator('.profile-name-form input').fill('QC Display Name')
  await qc.page.getByRole('button', { name: 'Save display name', exact: true }).click()
  await expect(qc.page.locator('.user-label')).toContainText('QC Display Name')
  await expect(qc.page.locator('.profile-statistics')).toContainText('Recent login activity')
  const changedPassword = `Changed_${randomUUID()}!`
  await qc.page
    .getByLabel('Current password', { exact: true })
    .fill(process.env.BOOKING_E2E_PASSWORD)
  await qc.page.getByLabel('New password', { exact: true }).fill(changedPassword)
  await qc.page.getByLabel('Confirm new password', { exact: true }).fill(changedPassword)
  await qc.page.getByRole('button', { name: 'Change password', exact: true }).click()
  await expect(qc.page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  await qc.ctx.close()
  const again = await login('qc', changedPassword)
  await expect(again.page.locator('.user-label')).toContainText('QC Display Name')
  await go(page, '/admin/users')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true)
  await page.screenshot({
    path: path.join(artifacts, 'admin-mobile.png'),
    fullPage: true,
  })
  expect(errors).toEqual([])
  await again.ctx.close()
  await a.ctx.close()
  await agent.ctx.close()
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally {
  await browser.close()
}
