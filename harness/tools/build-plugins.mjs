// Builds the browser halves of the Workspace plugins (lib/client.js) from their templates:
// - dsh-workspace-brand: inlines the official brand assets from docs/manual/assets;
// - dsh-workspace-it: inlines the Italian dictionaries from i18n/*.json.
// Usage (from harness/):  node tools/build-plugins.mjs
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const harness = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const assets = path.resolve(harness, '..', 'docs', 'manual', 'assets')
const plugins = path.join(harness, 'plugins')

const dataUri = (file, mime) => `data:${mime};base64,${fs.readFileSync(path.join(assets, file)).toString('base64')}`

function build(plugin, replacements) {
  const dir = path.join(plugins, plugin)
  let source = fs.readFileSync(path.join(dir, 'src', 'client.template.js'), 'utf8')
  for (const [key, value] of Object.entries(replacements)) {
    const count = source.split(key).length - 1
    if (count !== 1) throw new Error(`${plugin}: placeholder ${key} found ${count} times in the template, expected once`)
    source = source.replace(key, () => JSON.stringify(value, null, '\t').replace(/\n/g, '\n\t\t'))
  }
  const out = path.join(dir, 'lib', 'client.js')
  fs.writeFileSync(out, source)
  console.log(`${path.relative(harness, out)} (${Math.round(fs.statSync(out).size / 1024)} KB)`)
}

build('dsh-workspace-brand', {
  __LOGO_POSITIVE__: dataUri('logo-positivo.svg', 'image/svg+xml'),
  __LOGO_NEGATIVE__: dataUri('logo-negativo.svg', 'image/svg+xml'),
  __ICON_PNG__: dataUri('icona.png', 'image/png'),
  __LEXEND_WOFF2__: dataUri('lexend-latin.woff2', 'font/woff2'),
})

const i18n = path.join(plugins, 'dsh-workspace-it', 'i18n')
const dictionaries = {}
for (const file of fs.readdirSync(i18n).filter((f) => f.endsWith('.json')).sort()) {
  const ns = file.slice(0, -'.json'.length)
  const entries = JSON.parse(fs.readFileSync(path.join(i18n, file), 'utf8'))
  // Files keep the English source next to each translation: { key: { en, it } }.
  const translated = Object.entries(entries).filter(([, v]) => v.it).map(([k, v]) => [k, v.it])
  if (translated.length) dictionaries[ns] = Object.fromEntries(translated)
}
build('dsh-workspace-it', { __DICTIONARIES__: dictionaries })
