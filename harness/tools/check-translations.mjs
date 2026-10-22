// Checks the Italian dictionaries in plugins/dsh-workspace-it/i18n: every English entry has a
// translation, and each translation keeps the same {placeholders}, markup tags and code spans.
// Usage (from harness/):  node tools/check-translations.mjs      exit code 1 on problems
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const harness = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const i18n = path.join(harness, 'plugins', 'dsh-workspace-it', 'i18n')

const tokens = (text) => [
  ...(text.match(/\{[^{}\s]+\}/g) ?? []),          // {placeholder}
  ...(text.match(/<\/?[a-zA-Z][^>]*>/g) ?? []),     // <tag>
  ...(text.match(/`[^`]+`/g) ?? []),                // `code`
].sort()

let total = 0, missing = 0
const problems = []
for (const file of fs.readdirSync(i18n).filter((f) => f.endsWith('.json')).sort()) {
  const ns = file.slice(0, -5)
  const entries = JSON.parse(fs.readFileSync(path.join(i18n, file), 'utf8'))
  for (const [key, { en, it }] of Object.entries(entries)) {
    total++
    if (!it) { missing++; continue }
    const a = tokens(en), b = tokens(it)
    if (JSON.stringify(a) !== JSON.stringify(b)) problems.push(`${ns} › ${key}: ${JSON.stringify(a)} ≠ ${JSON.stringify(b)}`)
  }
}
console.log(`Stringhe: ${total}, tradotte: ${total - missing}, mancanti: ${missing}, segnaposto diversi: ${problems.length}`)
for (const p of problems) console.log('  ' + p)
process.exit(missing || problems.length ? 1 : 0)
