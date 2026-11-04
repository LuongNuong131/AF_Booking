import { chromium, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
const browser = await chromium.launch({
  headless: true,
  ...(process.env.BOOKING_CHROMIUM_PATH
    ? { executablePath: process.env.BOOKING_CHROMIUM_PATH }
    : {}),
})
const errors = []
const API = process.env.BOOKING_E2E_API_URL
async function pageIn(context) {
  const page = await context.newPage()
  page.on('pageerror', (e) => errors.push(e.name))
  return page
}
async function login(page, name, password = process.env.BOOKING_E2E_PASSWORD) {
  await expect(async () => {
    await page.goto('http://localhost:5173/login')
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  }).toPass({ timeout: 15000 })
  await page.getByLabel('Username', { exact: true }).fill(name)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
}
const live = (page) => page.getByLabel('Realtime connection: Live', { exact: true })
try {
  const context = await browser.newContext(),
    leader = await pageIn(context)
  const sockets = new Set(),
    seen = new WeakSet(),
    attached = new WeakSet()
  let opened = 0
  const observe = (page) => {
    if (attached.has(page)) return
    attached.add(page)
    page.on('websocket', (ws) => {
      if (new URL(ws.url()).pathname !== '/api/v1/ws' || seen.has(ws)) return
      seen.add(ws)
      opened++
      sockets.add(ws)
      ws.on('close', () => sockets.delete(ws))
      // Playwright may destroy the target before emitting each WebSocket close.
      page.once('close', () => sockets.delete(ws))
    })
  }
  context.on('page', observe)
  observe(leader)
  await login(leader, 'agent')
  await expect(live(leader)).toBeVisible()
  const follower = await pageIn(context)
  await follower.goto('http://localhost:5173')
  await expect(live(follower)).toBeVisible()
  await expect(live(leader)).toBeVisible()
  await expect.poll(() => sockets.size).toBe(1)
  const ownership = await follower.evaluate(async () => {
    const state = await navigator.locks.query()
    return {
      held: state.held.filter((lock) => lock.name.startsWith('booking.realtime.')).length,
      pending: state.pending.filter((lock) => lock.name.startsWith('booking.realtime.')).length,
    }
  })
  expect(ownership.held).toBe(1)
  expect(ownership.pending).toBe(1)
  const beforeHandoff = opened
  await leader.close()
  await expect(live(follower)).toBeVisible()
  await expect.poll(() => opened).toBeGreaterThan(beforeHandoff)
  await expect.poll(() => sockets.size).toBe(1)
  const third = await pageIn(context)
  await third.goto('http://localhost:5173')
  await expect(live(third)).toBeVisible()
  await expect(live(follower)).toBeVisible()
  await expect.poll(() => sockets.size).toBe(1)
  // A logout in either tab removes the same shared token and private workspace in both.
  await follower.goto('http://localhost:5173/profile')
  await expect(live(follower)).toBeVisible()
  await follower.getByRole('button', { name: 'Sign out', exact: true }).click()
  for (const page of [follower, third]) {
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
    expect(await page.evaluate(() => localStorage.getItem('booking.access_token'))).toBeNull()
    await expect(page.locator('.booking-summary-card')).toHaveCount(0)
  }
  const adminContext = await browser.newContext(),
    admin = await pageIn(adminContext)
  await login(admin, 'admin')
  await expect(live(admin)).toBeVisible()
  const bearer = await admin.evaluate(() => localStorage.getItem('booking.access_token'))
  const temporary = `Temporary_${randomUUID()}!`,
    permanent = `Permanent_${randomUUID()}!`
  const response = await admin.request.post(API + '/admin/users', {
    headers: { Authorization: 'Bearer ' + bearer },
    data: {
      username: 'security.agent',
      full_name: 'Security Agent',
      role: 'agent',
      temporary_password: temporary,
    },
  })
  expect(response.status()).toBe(200)
  const restrictedContext = await browser.newContext(),
    restricted = await pageIn(restrictedContext)
  let restrictedSockets = 0
  restricted.on('websocket', (ws) => {
    if (new URL(ws.url()).pathname === '/api/v1/ws') restrictedSockets++
  })
  await login(restricted, 'security.agent', temporary)
  await expect(
    restricted.getByRole('heading', { name: 'Change your temporary password', exact: true }),
  ).toBeVisible()
  expect(restrictedSockets).toBe(0)
  await restricted.goto('http://localhost:5173/summary')
  await expect(restricted).toHaveURL('http://localhost:5173/change-password')
  await restricted.getByLabel('Current password', { exact: true }).fill(temporary)
  await restricted.getByLabel('New password', { exact: true }).fill(permanent)
  await restricted.getByLabel('Confirm new password', { exact: true }).fill(permanent)
  await restricted.getByRole('button', { name: 'Change password', exact: true }).click()
  await expect(restricted.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  expect(
    await restricted.evaluate(() => localStorage.getItem('booking.access_token')),
  ).toBeNull()
  await login(restricted, 'security.agent', permanent)
  await expect(live(restricted)).toBeVisible()
  expect(errors).toEqual([])
  process.stdout.write(JSON.stringify({ result: 'passed' }) + '\n')
} finally {
  await browser.close()
}
