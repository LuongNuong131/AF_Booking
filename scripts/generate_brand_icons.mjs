// Raster asset preparation only: keep the approved AF design and export web sizes.
import { readFile, writeFile } from 'node:fs/promises'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'
const source = process.argv[2]
if (!source) throw new Error('Usage: node scripts/generate_brand_icons.mjs SOURCE.png')
const browser = await chromium.launch({ headless: true, ...(process.env.BOOKING_CHROMIUM_PATH ? { executablePath: process.env.BOOKING_CHROMIUM_PATH } : {}) })
try {
  const page = await browser.newPage()
  const input = 'data:image/png;base64,' + (await readFile(source)).toString('base64')
  const images = await page.evaluate(async src => {
    const img = new Image()
    img.src = src
    await img.decode()
    return [32, 180, 192, 256, 512].map(size => {
      const canvas = document.createElement('canvas')
      canvas.width = canvas.height = size
      const ctx = canvas.getContext('2d')
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, size, size)
      ctx.drawImage(img, 0, 0, size, size)
      // Normalize near-white/near-black noise while keeping anti-aliased edges.
      const pixels = ctx.getImageData(0, 0, size, size)
      for (let i = 0; i < pixels.data.length; i += 4) {
        const values = [pixels.data[i], pixels.data[i + 1], pixels.data[i + 2]]
        const fill = Math.min(...values) > 230 ? 255 : Math.max(...values) < 25 ? 0 : null
        if (fill !== null) pixels.data[i] = pixels.data[i + 1] = pixels.data[i + 2] = fill
      }
      ctx.putImageData(pixels, 0, 0)
      return { size, data: canvas.toDataURL('image/png').split(',')[1] }
    })
  }, input)
  for (const { size, data } of images) {
    const file = size === 256 ? 'brand/af-logo.png' : `icons/icon-${size}.png`
    await writeFile(new URL('../frontend/public/' + file, import.meta.url), Buffer.from(data, 'base64'))
  }
} finally { await browser.close() }
