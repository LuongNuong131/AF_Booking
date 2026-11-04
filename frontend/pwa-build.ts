import { readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { resolve, relative } from 'node:path'
import { createHash } from 'node:crypto'
import type { Plugin } from 'vite'
export function staticPwa(): Plugin {
  return {
    name: 'static-only-pwa',
    apply: 'build',
    closeBundle() {
      const root = resolve('dist'),
        files: string[] = []
      function walk(dir: string) {
        for (const item of readdirSync(dir, { withFileTypes: true })) {
          const path = resolve(dir, item.name)
          if (item.isDirectory()) walk(path)
          else if (
            /\.(?:html|css|js|woff2|png|svg|webmanifest)$/.test(item.name) &&
            item.name !== 'sw.js'
          )
            files.push(path)
        }
      }
      walk(root)
      files.sort()
      const template = readFileSync(resolve('src/pwa/service-worker.js'), 'utf8'),
        hash = createHash('sha256').update(template)
      for (const file of files) hash.update(readFileSync(file))
      const source = template
        .replace(
          '__PRECACHE__',
          JSON.stringify(files.map((file) => '/' + relative(root, file).replaceAll('\\', '/'))),
        )
        .replace('__BUILD_ID__', JSON.stringify(hash.digest('hex').slice(0, 24)))
      writeFileSync(resolve(root, 'sw.js'), source)
    },
  }
}
