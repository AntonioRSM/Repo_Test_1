// Extracts the English UI dictionaries of the installed DeepSeek Harness and updates
// plugins/dsh-workspace-it/i18n/<namespace>.json ({ key: { en, it } }), keeping existing Italian
// translations and flagging new or changed English text. Static analysis only: each bundle is
// parsed with acorn and only string literals are read; no package code is evaluated.
// Usage (from harness/, after npm install):  node tools/extract-strings.mjs
import fs from 'node:fs'
import path from 'node:path'
import * as acorn from 'acorn'
import * as walk from 'acorn-walk'

import { fileURLToPath } from 'node:url'
const harness = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const root = path.join(harness, 'node_modules', '@deepseek-ai')
const i18n = path.join(harness, 'plugins', 'dsh-workspace-it', 'i18n')
const result = {}   // ns -> { key: { en, zh } }
const report = []

let strings = new Map(), aliases = new Map(), dicts = new Map()
function str(node) {
  if (!node) return undefined
  if (node.type === 'Literal' && typeof node.value === 'string') return node.value
  if (node.type === 'Identifier') return strings.get(node.name)
  if (node.type === 'TemplateLiteral') {
    let out = node.quasis[0].value.cooked
    for (let i = 0; i < node.expressions.length; i++) {
      const v = str(node.expressions[i]); if (v === undefined) return undefined
      out += v + node.quasis[i + 1].value.cooked
    }
    return out
  }
  // ["paragraph", "paragraph"].join("\n\n")
  if (node.type === 'CallExpression' && node.callee.type === 'MemberExpression' && node.callee.property.name === 'join' &&
      node.callee.object.type === 'ArrayExpression') {
    const parts = node.callee.object.elements.map(str)
    const sep = node.arguments.length ? str(node.arguments[0]) : ','
    return parts.includes(undefined) || sep === undefined ? undefined : parts.join(sep)
  }
  if (node.type === 'BinaryExpression' && node.operator === '+') {
    const a = str(node.left), b = str(node.right)
    return a === undefined || b === undefined ? undefined : a + b
  }
  return undefined
}
function literalObject(node) {
  if (node?.type !== 'ObjectExpression') return null
  const dict = {}
  for (const p of node.properties) {
    if (p.type === 'SpreadElement' && p.argument.type === 'Identifier' && dicts.has(p.argument.name)) {
      Object.assign(dict, dicts.get(p.argument.name)); continue
    }
    if (p.type !== 'Property' || p.computed) return null
    const key = p.key.type === 'Literal' ? String(p.key.value) : p.key.type === 'Identifier' ? p.key.name : null
    if (key == null) return null
    const v = str(p.value)
    if (v === undefined) return null
    dict[key] = v
  }
  return dict
}

for (const pkg of fs.readdirSync(root)) {
  const lib = path.join(root, pkg, 'lib')
  if (!fs.existsSync(lib)) continue
  for (const file of fs.readdirSync(lib).filter((f) => f.endsWith('.js'))) {
    const src = fs.readFileSync(path.join(lib, file), 'utf8')
    if (!src.includes('register(')) continue
    let ast
    try { ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'module', allowHashBang: true }) }
    catch (e) { report.push(`${pkg}/${file}: parse error ${e.message}`); continue }
    dicts = new Map(); strings = new Map(); aliases = new Map()
    const decls = []
    walk.full(ast, (n) => { if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier' && n.init) decls.push(n) })
    for (let pass = 0; pass < 4; pass++) for (const n of decls) {
      const v = str(n.init); if (v !== undefined) strings.set(n.id.name, v)
    }
    for (let pass = 0; pass < 3; pass++) for (const n of decls) {
      const d = literalObject(n.init)
      if (d) dicts.set(n.id.name, d)
      if (n.init.type === 'Identifier') aliases.set(n.id.name, n.init.name)
    }
    const deref = (name) => { let seen = 0; while (!dicts.has(name) && aliases.has(name) && seen++ < 10) name = aliases.get(name); return dicts.get(name) }
    const resolveDict = (node) => node?.type === 'Identifier' ? deref(node.name) : literalObject(node)
    const resolveStr = (node) => str(node)
    walk.full(ast, (n) => {
      if (n.type !== 'CallExpression' || n.callee.type !== 'MemberExpression' || n.callee.property.name !== 'register') return
      const obj = n.callee.object
      const isLocale = (obj.type === 'Identifier' && /locale/i.test(obj.name)) ||
        (obj.type === 'MemberExpression' && obj.property.name === 'locale')
      if (!isLocale) return
      const ns = resolveStr(n.arguments[0])
      if (typeof ns !== 'string') { report.push(`${pkg}/${file}: unresolved ns`); return }
      let en, zh
      if (n.arguments.length >= 3) {
        const loc = resolveStr(n.arguments[1])
        if (loc === 'en') en = resolveDict(n.arguments[2])
        if (loc === 'zh') zh = resolveDict(n.arguments[2])
        // for (const [locale, dict] of [["en", {...}], ["zh", {...}]]) register(ns, locale, dict)
        if (loc === undefined) {
          for (const d of decls.filter((d) => d.init.type === 'ArrayExpression' && d.start < n.start)) {
            for (const pair of d.init.elements) {
              if (pair?.type !== 'ArrayExpression' || pair.elements.length !== 2) continue
              const id = str(pair.elements[0])
              if (id === 'en') en ??= resolveDict(pair.elements[1])
              if (id === 'zh') zh ??= resolveDict(pair.elements[1])
            }
          }
        }
      } else if (n.arguments[1]?.type === 'ObjectExpression') {
        for (const p of n.arguments[1].properties) {
          const k = p.key?.name ?? p.key?.value
          if (p.shorthand) {
            // Same-named consts can live in several scopes: take the closest one declared before the call.
            const near = (name) => { const c = decls.filter((d) => d.id.name === name && d.start < n.start).pop(); return c ? (literalObject(c.init) ?? resolveDict(c.init)) : undefined }
            if (k === 'en') en = near('en'); if (k === 'zh') zh = near('zh'); continue
          }
          if (k === 'en') en = resolveDict(p.value)
          if (k === 'zh') zh = resolveDict(p.value)
        }
      }
      if (!en) { report.push(`${pkg}/${file}: ns ${ns} without resolvable en`); return }
      const target = (result[ns] ??= {})
      for (const [k, v] of Object.entries(en)) target[k] = { en: v, zh: zh?.[k] ?? null, pkg }
    })
  }
}

fs.mkdirSync(i18n, { recursive: true })
let missing = 0, changed = 0, total = 0
for (const [ns, entries] of Object.entries(result).sort()) {
  const file = path.join(i18n, `${ns}.json`)
  const old = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {}
  const next = {}
  for (const [key, { en }] of Object.entries(entries)) {
    total++
    const prev = old[key]
    if (prev && prev.en === en && prev.it) next[key] = prev
    else {
      next[key] = { en, it: '' }
      if (prev?.it) { next[key].previous = prev.it; changed++ } else missing++
    }
  }
  fs.writeFileSync(file, JSON.stringify(next, null, 2) + '\n')
}
console.log(`namespaces: ${Object.keys(result).length}, keys: ${total}, da tradurre: ${missing}, testo inglese cambiato: ${changed}`)
if (report.length) console.log(report.join('\n'))
