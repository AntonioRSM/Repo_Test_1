// Prepares the profile's package.json at every launch (avvia.ps1) without losing the user's plugins.
// The dsh plugin manager writes installed plugins into this file (dependencies and dsh.profile.bundles):
// the template only adds what is missing — the Workspace bundles first — and never removes anything.
// Uso: node tools/prepara-profilo.mjs <modello package.json> <package.json del profilo>
import fs from 'node:fs'
import { pathToFileURL } from 'node:url'

export function unisciProfilo(modello, attuale) {
  const risultato = structuredClone(attuale)
  risultato.dependencies = { ...modello.dependencies, ...attuale.dependencies }
  risultato.dsh ??= {}
  risultato.dsh.profile ??= {}
  const utente = Array.isArray(risultato.dsh.profile.bundles) ? risultato.dsh.profile.bundles : []
  const obbligatori = modello.dsh.profile.bundles
  risultato.dsh.profile.bundles = [...obbligatori, ...utente.filter((b) => !obbligatori.includes(b))]
  for (const [chiave, valore] of Object.entries(modello)) if (!(chiave in risultato)) risultato[chiave] = valore
  return risultato
}

function leggi(file) {
  // trimStart() also drops a BOM left by Windows editors (U+FEFF counts as whitespace)
  return JSON.parse(fs.readFileSync(file, 'utf8').trimStart())
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [modelloFile, profiloFile] = process.argv.slice(2)
  const modello = leggi(modelloFile)
  let testo
  if (!fs.existsSync(profiloFile)) {
    testo = JSON.stringify(modello, null, 2) + '\n'
  } else {
    let attuale
    try {
      attuale = leggi(profiloFile)
    } catch {
      // Unreadable file: keep a copy for the user and start again from the template.
      fs.copyFileSync(profiloFile, `${profiloFile}.non-valido`)
      console.log(`package.json del profilo non valido: copia salvata in ${profiloFile}.non-valido`)
      attuale = {}
    }
    testo = JSON.stringify(unisciProfilo(modello, attuale), null, 2) + '\n'
    if (fs.existsSync(profiloFile) && fs.readFileSync(profiloFile, 'utf8') === testo) process.exit(0)
  }
  fs.writeFileSync(profiloFile, testo)
}
