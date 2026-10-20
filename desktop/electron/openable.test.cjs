"use strict";
// Test della logica di apertura file (Miglioramento #13 / Bug #18).
// Eseguire con: node --test electron/   (dalla cartella desktop)
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { assertOpenableTarget, makeSupportedExtensions } = require("./openable.cjs");

test("supportedExtensions: un errore non resta in cache (Bug #18)", async () => {
  let calls = 0;
  const engineFetch = async (route) => {
    calls += 1;
    if (calls === 1) throw new Error("/health: 503"); // motore non pronto
    assert.equal(route, "/health");
    return { supported_extensions: [".pdf", ".docx"] };
  };
  const supportedExtensions = makeSupportedExtensions(engineFetch);
  await assert.rejects(supportedExtensions(), /503/); // primo tentativo: fallisce
  const exts = await supportedExtensions(); // secondo: riprova e riesce
  assert.ok(exts instanceof Set);
  assert.ok(exts.has(".pdf"));
  await supportedExtensions(); // terzo: cache valida, nessuna chiamata in più
  assert.equal(calls, 2);
});

function makeEnv() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "wsos-openable-"));
  const source = path.join(root, "sorgente");
  fs.mkdirSync(source);
  const doc = path.join(source, "contratto.pdf");
  fs.writeFileSync(doc, "%PDF-1.4 fake");
  const exe = path.join(source, "programma.exe");
  fs.writeFileSync(exe, "MZ fake");
  const outside = path.join(root, "esterno.txt");
  fs.writeFileSync(outside, "fuori");
  const engineFetch = async (route) => {
    if (route === "/vaults") return [{ id: "v1", sources: [source] }];
    if (route === "/health") return { supported_extensions: [".pdf"] };
    throw new Error(`route inattesa: ${route}`);
  };
  return { root, source, doc, exe, outside, engineFetch, supportedExtensions: makeSupportedExtensions(engineFetch) };
}

test("assertOpenableTarget: documento supportato dentro un Vault apribile", async () => {
  const env = makeEnv();
  const safe = await assertOpenableTarget(env.doc, { forOpen: true, engineFetch: env.engineFetch, supportedExtensions: env.supportedExtensions });
  assert.equal(safe, fs.realpathSync(env.doc));
  fs.rmSync(env.root, { recursive: true, force: true });
});

test("assertOpenableTarget: .exe dentro il Vault NON apribile (solo 'mostra nella cartella')", async () => {
  const env = makeEnv();
  assert.equal(await assertOpenableTarget(env.exe, { forOpen: true, engineFetch: env.engineFetch, supportedExtensions: env.supportedExtensions }), null);
  // ma si può mostrare nella cartella
  assert.ok(await assertOpenableTarget(env.exe, { engineFetch: env.engineFetch, supportedExtensions: env.supportedExtensions }));
  fs.rmSync(env.root, { recursive: true, force: true });
});

test("assertOpenableTarget: file fuori dai Vault rifiutato", async () => {
  const env = makeEnv();
  assert.equal(await assertOpenableTarget(env.outside, { forOpen: true, engineFetch: env.engineFetch, supportedExtensions: env.supportedExtensions }), null);
  fs.rmSync(env.root, { recursive: true, force: true });
});

test("assertOpenableTarget: file inesistente rifiutato", async () => {
  const env = makeEnv();
  assert.equal(
    await assertOpenableTarget(path.join(env.source, "mancante.pdf"), { forOpen: true, engineFetch: env.engineFetch, supportedExtensions: env.supportedExtensions }),
    null,
  );
  fs.rmSync(env.root, { recursive: true, force: true });
});

test("assertOpenableTarget: motore non raggiungibile nega invece di supporre", async () => {
  const env = makeEnv();
  const failingFetch = async () => {
    throw new Error("engine not running");
  };
  assert.equal(await assertOpenableTarget(env.doc, { forOpen: true, engineFetch: failingFetch, supportedExtensions: makeSupportedExtensions(failingFetch) }), null);
  fs.rmSync(env.root, { recursive: true, force: true });
});
