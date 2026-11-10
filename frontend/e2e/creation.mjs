// Real authenticated Agent creation, duplicate prevention and responsive dialogs.
import { chromium, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const output = process.env.BOOKING_E2E_ARTIFACTS
await mkdir(output, { recursive: true })
const browser = await chromium.launch({
  headless: true,
  ...(process.env.BOOKING_CHROMIUM_PATH
    ? { executablePath: process.env.BOOKING_CHROMIUM_PATH }
    : {}),
})
const errors = []
const context = await browser.newContext({ viewport:{width:1440,height:1000}, reducedMotion:'reduce', colorScheme:'light' })
const page = await context.newPage()
page.on('pageerror', error => errors.push(error.message))
async function addDialog(key) {
  await page.locator('.create-booking-trigger').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.locator('#create-booking-key').fill(key)
  return dialog
}
async function confirmSimilar(dialog) {
  const check = dialog.locator('.create-booking-similar input[type="checkbox"]')
  if (await check.count()) await check.check()
}
try {
  await expect(async () => {
    await page.goto('http://localhost:5173/login')
    await expect(page.locator('input[type="password"]')).toBeVisible()
  }).toPass({timeout:15000})
  await page.screenshot({path:path.join(output,'login-premium-desktop.png'),fullPage:true})
  await page.getByLabel('Username',{exact:true}).fill('agent')
  await page.getByLabel('Password',{exact:true}).fill(process.env.BOOKING_E2E_PASSWORD)
  await page.getByRole('button',{name:'Sign in',exact:true}).click()
  await expect(page.locator('.topbar')).toBeVisible()
  await expect(page.getByRole('link',{name:'Admin',exact:true})).toHaveCount(0)
  await page.screenshot({path:path.join(output,'workspace-premium-desktop.png'),fullPage:true})

  let dialog = await addDialog('cw 9998800 - rdu - 2611')
  await expect(dialog.locator('#create-booking-supplier')).toBeVisible()
  await dialog.locator('#create-booking-supplier').fill('Aurora Crew Hotel')
  await dialog.locator('#create-booking-type').selectOption('hotel')
  await confirmSimilar(dialog)
  await page.screenshot({path:path.join(output,'add-booking-desktop.png'),fullPage:true})
  await dialog.getByRole('button',{name:'Add booking',exact:true}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.booking-summary-card')).toContainText('Aurora Crew Hotel')
  await expect(page.locator('.booking-summary-card')).toContainText('9998800')
  await page.screenshot({path:path.join(output,'created-booking-desktop.png'),fullPage:true})

  dialog = await addDialog('CW 9998800–RDU–2611')
  await expect(dialog).toContainText('This booking already exists')
  await expect(dialog.getByRole('button',{name:'Add booking',exact:true})).toBeDisabled()
  await expect(dialog.locator('#create-booking-supplier')).toHaveCount(0)
  await page.screenshot({path:path.join(output,'duplicate-booking-desktop.png'),fullPage:true})
  await dialog.getByRole('button',{name:'Close',exact:true}).click()

  dialog = await addDialog('CW9998800-RDU-2612')
  await expect(dialog.locator('.create-booking-supplier')).toContainText('Aurora Crew Hotel')
  await expect(dialog.locator('#create-booking-supplier')).toHaveCount(0)
  await confirmSimilar(dialog)
  await dialog.getByRole('button',{name:'Add booking',exact:true}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.booking-summary-card')).toContainText('2612')

  // A new station gets its own supplier folder, even when this CW exists elsewhere.
  dialog = await addDialog('CW9998800-YUL-2611')
  await expect(dialog.locator('#create-booking-supplier')).toBeVisible()
  await dialog.locator('#create-booking-supplier').fill('Montreal Crew Hotel')
  await confirmSimilar(dialog)
  await dialog.getByRole('button',{name:'Add booking',exact:true}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.booking-summary-card')).toContainText('Montreal Crew Hotel')
  await expect(page.locator('.booking-summary-card')).toContainText('YUL')

  // The number becomes occupied after precheck: the real server must reject it.
  dialog = await addDialog('CW9998800-RDU-2701')
  await expect(dialog.locator('.create-booking-supplier')).toContainText('Aurora Crew Hotel')
  await confirmSimilar(dialog)
  const token = await page.evaluate(() => localStorage.getItem('booking.access_token'))
  const competing = await page.request.post(process.env.BOOKING_E2E_API_URL + '/bookings', {
    headers:{Authorization:'Bearer ' + token},
    data:{booking_key:'CW9998800-RDU-2701',confirm_new:true},
  })
  expect(competing.status()).toBe(201)
  await dialog.getByRole('button',{name:'Add booking',exact:true}).click()
  await expect(dialog).toContainText('This booking already exists')
  await expect(dialog.getByRole('button',{name:'Add booking',exact:true})).toBeDisabled()
  await dialog.getByRole('button',{name:'Open booking',exact:true}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.booking-summary-card')).toContainText('2701')

  for (const width of [375,768,1024,1440]) {
    await page.setViewportSize({width,height:900})
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1)
  }
  await page.setViewportSize({width:375,height:844})
  dialog = await addDialog('CW9998800-RDU-2701')
  await expect(dialog).toContainText('This booking already exists')
  const bounds = await dialog.boundingBox()
  expect(bounds.x).toBeGreaterThanOrEqual(0)
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(376)
  await page.screenshot({path:path.join(output,'duplicate-booking-mobile.png'),fullPage:true})
  await dialog.getByRole('button',{name:'Close',exact:true}).click()
  await page.getByTitle('Appearance',{exact:true}).click()
  await page.getByRole('menuitemradio',{name:'Dark',exact:true}).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme','dark')
  await page.screenshot({path:path.join(output,'workspace-premium-mobile-dark.png'),fullPage:true})
  expect(errors).toEqual([])
  process.stdout.write(JSON.stringify({result:'passed'}) + '\n')
} finally {
  await context.close()
  await browser.close()
}
