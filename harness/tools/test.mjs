// Workspace Harness checks (npm test): translations, generated plugins, composed profile.
// The profile check builds a throwaway DSH_HOME from profile/ and asks the installed dsh to compose
// it (--dump-config): nothing boots, no port is opened.
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const harness = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const run = (args, env = {}) => execFileSync(process.execPath, args, { cwd: harness, env: { ...process.env, ...env }, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
let failed = 0
function check(name, fn) {
  try { fn(); console.log(`ok   ${name}`) } catch (e) { failed++; console.log(`FAIL ${name}\n     ${String(e.stdout || e.message).trim().split('\n').join('\n     ')}`) }
}

check('traduzioni complete e segnaposto coerenti', () => run(['tools/check-translations.mjs']))

for (const plugin of ['dsh-workspace-brand', 'dsh-workspace-it']) {
  check(`${plugin}: lib/client.js generato e sintatticamente valido`, () => {
    const file = path.join(harness, 'plugins', plugin, 'lib', 'client.js')
    if (/__[A-Z_]+__/.test(fs.readFileSync(file, 'utf8'))) throw new Error('segnaposto non sostituiti: eseguire node tools/build-plugins.mjs')
    run(['--check', file])
  })
}

check('dizionari italiani aggiornati rispetto a i18n/', () => {
  const client = fs.readFileSync(path.join(harness, 'plugins', 'dsh-workspace-it', 'lib', 'client.js'), 'utf8')
  const i18n = path.join(harness, 'plugins', 'dsh-workspace-it', 'i18n')
  for (const file of fs.readdirSync(i18n)) {
    for (const { it } of Object.values(JSON.parse(fs.readFileSync(path.join(i18n, file), 'utf8')))) {
      if (it && !client.includes(JSON.stringify(it).slice(1, -1))) throw new Error(`${file}: lib/client.js non aggiornato, eseguire node tools/build-plugins.mjs`)
    }
  }
})

check('package.json del profilo: plugin utente conservati (Bug #23)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wsos-profilo-test-'))
  try {
    const modello = path.join(harness, 'profile', 'package.json')
    const profilo = path.join(dir, 'package.json')
    const prepara = () => run(['tools/prepara-profilo.mjs', modello, profilo])
    const leggi = () => JSON.parse(fs.readFileSync(profilo, 'utf8'))
    prepara()
    const iniziale = leggi()
    if (JSON.stringify(iniziale) !== JSON.stringify(JSON.parse(fs.readFileSync(modello, 'utf8')))) throw new Error('primo avvio: il profilo non è il modello')
    // what the dsh plugin manager writes when the user adds a plugin; one Workspace bundle lost by hand
    iniziale.dependencies['@x/plugin'] = '1.0.0'
    iniziale.dsh.profile.bundles = ['@deepseek-ai/dsh-base', '@x/plugin']
    fs.writeFileSync(profilo, String.fromCharCode(0xfeff) + JSON.stringify(iniziale))
    prepara()
    const dopo = leggi()
    if (dopo.dependencies['@x/plugin'] !== '1.0.0') throw new Error('dipendenza del plugin utente persa')
    const attesi = ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app', '@workspace-sm/dsh-workspace', '@x/plugin']
    if (JSON.stringify(dopo.dsh.profile.bundles) !== JSON.stringify(attesi)) throw new Error(`bundle: ${dopo.dsh.profile.bundles}`)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

const dsh = path.join(harness, 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js')
if (!fs.existsSync(dsh)) {
  console.log('skip profilo composto (runtime non installato: npm install)')
} else {
  check('profilo workspace composto da dsh', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'wsos-harness-test-'))
    try {
      const profile = path.join(home, 'profiles', 'workspace')
      fs.mkdirSync(path.join(profile, 'node_modules', '@workspace-sm'), { recursive: true })
      for (const f of fs.readdirSync(path.join(harness, 'profile'))) fs.copyFileSync(path.join(harness, 'profile', f), path.join(profile, f))
      for (const p of ['dsh-workspace-brand', 'dsh-workspace-it']) {
        fs.symlinkSync(path.join(harness, 'plugins', p), path.join(profile, 'node_modules', '@workspace-sm', p), 'junction')
      }
      const providers = { 'ollama-locale': { api: 'openai-completions', baseURL: 'http://127.0.0.1:11434/v1', apiKeyEnv: 'WSOS_LOCAL_LLM_KEY', models: [{ id: 'workspace-agent:latest' }] } }
      const dump = run([dsh, '--profile', 'workspace', '--dump-config'], {
        DSH_HOME: home, WSOS_DSH_PROVIDERS: JSON.stringify(providers), WSOS_DSH_PROVIDER: 'ollama-locale', WSOS_DSH_MODEL: 'workspace-agent:latest',
      })
      const expect = [
        [/id: locale\n\s+name: '@deepseek-ai\/dsh-client-locale'\n\s+config:\n\s+preference: it/, 'italiano come lingua predefinita'],
        [/textFontFamily: Lexend/, 'Lexend come carattere del testo'],
        [/id: ui-brand-official\n\s+name: '[^']+'\n\s+disabled: true/, 'marchio ufficiale DeepSeek disattivato'],
        [/name: '@workspace-sm\/dsh-workspace-brand'/, 'plugin del marchio Workspace montato'],
        [/name: '@workspace-sm\/dsh-workspace-it'/, 'pacchetto di lingua italiano montato'],
        [/Rispondi sempre in italiano/, "istruzione all'agente di rispondere in italiano"],
      ]
      for (const [re, what] of expect) if (!re.test(dump.replace(/\r\n/g, '\n'))) throw new Error(`manca: ${what}`)
    } finally {
      fs.rmSync(home, { recursive: true, force: true })
    }
  })
}

console.log(failed ? `\n${failed} controlli non superati` : '\nTutti i controlli superati')
process.exit(failed ? 1 : 0)
