"use strict";
// Logica di apertura file estratta da main.cjs (Miglioramento #13): qui non ci sono
// dipendenze da Electron, così si può testare con `node --test`.
// Solo file dentro le cartelle sorgenti di un Vault possono essere aperti: il renderer
// può ricevere percorsi arbitrari (prompt injection, stato corrotto) e shell.openPath
// su un eseguibile lo farebbe partire.

const fs = require("node:fs");
const path = require("node:path");

function makeSupportedExtensions(engineFetch) {
  // Cache a primo uso delle estensioni documento esposte dal motore su /health.
  let cache = null;
  return async function supportedExtensions() {
    if (cache === null) {
      cache = engineFetch("/health").then(
        (h) => new Set((h.supported_extensions ?? []).map((e) => String(e).toLowerCase())),
      );
      // Bug #18: una promessa RIFIUTATA non va messa in cache. Se la prima richiesta
      // capita mentre il motore non è pronto, ogni apertura successiva falliva subito
      // fino al riavvio dell'app. L'errore svuota la cache: il tentativo dopo riprova.
      cache = cache.catch((err) => {
        cache = null;
        throw err;
      });
    }
    return cache;
  };
}

async function assertOpenableTarget(target, { forOpen = false, engineFetch, supportedExtensions }) {
  let resolved;
  try {
    // realpath segue symlink/giunzioni: un collegamento dentro una sorgente non deve
    // puntare silenziosamente fuori di essa (Miglioramento #8).
    resolved = fs.realpathSync(path.resolve(String(target)));
  } catch {
    return null; // deve esistere
  }
  let stat;
  try {
    stat = fs.statSync(resolved);
  } catch {
    return null;
  }
  if (!stat.isFile()) return null;
  let vaults, exts;
  try {
    [vaults, exts] = await Promise.all([engineFetch("/vaults"), forOpen ? supportedExtensions() : Promise.resolve(null)]);
  } catch {
    return null; // motore non raggiungibile: meglio negare che supporre
  }
  const normalized = resolved.toLowerCase();
  const inside = (vaults ?? []).some((v) =>
    (v.sources ?? []).some((s) => {
      let root;
      try {
        root = fs.realpathSync(path.resolve(String(s))).toLowerCase();
      } catch {
        root = path.resolve(String(s)).toLowerCase();
      }
      return normalized === root || normalized.startsWith(root + path.sep);
    }),
  );
  if (!inside) return null;
  // Per i tipi non ammessi l'interfaccia tiene solo "mostra nella cartella" (nessuna esecuzione).
  if (forOpen && (!(exts instanceof Set) || !exts.has(path.extname(resolved).toLowerCase()))) return null;
  return resolved;
}

module.exports = { assertOpenableTarget, makeSupportedExtensions };
