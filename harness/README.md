# Workspace Harness

Agente locale in italiano basato su [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
(licenza MIT), integrato in Workspace OS con il marchio Workspace S.r.l. e collegato ai modelli locali
di Ollama e LM Studio.

Il codice di DeepSeek non viene modificato. Il runtime ufficiale (`@deepseek-ai/dsh`, versione fissata
`0.2.1-rc.2`) si installa da npm, e tutto il resto passa dai punti di estensione previsti da dsh:
profili, livelli di patch, slot dell'interfaccia, pacchetti di lingua e temi.

```
harness/
  package.json              runtime fissato + plugin Workspace (dipendenze file:)
  avvia.ps1                 avvio: banner, profilo, modelli locali, porta libera, browser
  profile/                  modello del profilo "workspace" (bundle e livello utente iniziale)
  plugins/
    dsh-workspace/          livello di profilo: italiano, Lexend, marchio, rotte Ollama/LM Studio
    dsh-workspace-brand/    marchio: logo, icona, favicon, palette, Lexend, titolo della finestra
    dsh-workspace-it/       pacchetto di lingua italiano (2.906 stringhe in 64 namespace)
  tools/
    build-plugins.mjs       genera lib/client.js dei plugin (asset del marchio e dizionari)
    extract-strings.mjs     estrae i testi inglesi del runtime installato in i18n/*.json
    check-translations.mjs  verifica traduzioni mancanti e segnaposto {..}
```

## Come funziona

| Livello | Cosa fa |
|---|---|
| Profilo `workspace` | In `%LOCALAPPDATA%\WorkspaceOS\harness` (DSH_HOME dedicata, separata da un eventuale dsh personale). Bundle: `dsh-base`, `dsh-web-app`, `@workspace-sm/dsh-workspace` |
| `dsh-workspace` | Imposta l'italiano e Lexend come predefiniti, disattiva il marchio ufficiale DeepSeek (`ui-brand-official`) e monta i due plugin Workspace; registra le rotte dei modelli locali e il modello predefinito; chiede all'agente di rispondere in italiano |
| `dsh-workspace-brand` | Occupa gli slot `sidebar.brand.*` e `conversation.hero.brand.mark`, sostituisce favicon e nome nella finestra, sovrascrive i token del tema (`--dsw-alias-*`) con la palette Workspace in chiaro e scuro e carica Lexend |
| `dsh-workspace-it` | Registra la lingua `it` (ripiego `en`) e i dizionari di tutti i namespace con l'API pubblica `ctx.locale` |
| `avvia.ps1` | Prepara il profilo, collega i plugin, rileva i modelli di Ollama e LM Studio, sceglie una porta libera, traduce i messaggi di avvio e apre il browser |

Tutti i livelli Workspace hanno priorità più bassa delle scelte dell'utente: lingua, carattere,
modelli e provider cambiati nelle Impostazioni restano validi.

### Marchio (linee guida Workspace v1.0)

- Logo alla larghezza minima di 200 px, positivo su fondo chiaro e negativo su fondo scuro.
- Icona a 48 px (dimensione minima) nell'area iniziale della conversazione e come favicon (unica eccezione
  ammessa sotto i 48 px). Lo slot da 24 px della barra laterale resta vuoto, per non scendere sotto il minimo.
- Palette: Azzurro `#2E6BD6` (accento), Inchiostro `#16181D` (testi, fondo scuro), Grigio `#6B6F78` e
  Grigio chiaro `#A4A7AF` (testi secondari), Carta `#F4F2EC` (fondo chiaro).
- Lexend 400 per i testi e 600 per i titoli. Il logotipo usa sempre i file ufficiali, mai il carattere.
- Il banner di `avvia.ps1` usa il chevron `>` e il cursore azzurro con `sm`.

### Modelli locali

`avvia.ps1` legge i modelli da Ollama (`/api/tags`, escludendo quelli solo embedding) e da LM Studio
(`/api/v0/models`) e li passa al profilo come rotte `ollama-locale` e `lmstudio-locale`
(protocollo OpenAI Chat Completions). Il prompt dell'agente occupa circa 8.500 token, quindi:

- con Ollama l'installer crea **`workspace-agent`**: lo stesso LLM installato (`qwen3:4b-instruct`) con
  un contesto di 16.384 token, senza scaricare nulla; l'avvio lo usa come modello predefinito;
- con LM Studio carica il modello con una lunghezza di contesto di almeno 16.384 token.

Su un PC senza GPU dedicata la prima risposta può richiedere alcuni minuti: il modello deve leggere
l'intero prompt. Con una GPU o un modello cloud configurato dalla pagina **Modelli** i tempi scendono
a pochi secondi.

## Installazione e avvio

`INSTALLA.bat` chiede se installare Workspace Harness (circa 830 MB); `INSTALLA.bat -Harness` lo
installa senza chiedere, `-SenzaHarness` lo salta. Nel menu Start compare **Workspace Harness**.

A mano, dalla cartella `harness`:

```powershell
npm install --omit=dev
powershell -ExecutionPolicy Bypass -File avvia.ps1
```

La cartella di lavoro predefinita è `Documenti\Workspace Harness`.

## Aggiornare DeepSeek Harness

1. Cambia la versione di `@deepseek-ai/dsh` in `package.json` e i limiti `engines.dsh` dei tre plugin.
2. `npm install` (con le dipendenze di sviluppo), poi `node tools/extract-strings.mjs`: aggiorna
   `i18n/*.json`, conserva le traduzioni esistenti e segnala i testi nuovi o cambiati.
3. Traduci le voci con `"it": ""`, poi `node tools/check-translations.mjs` e `node tools/build-plugins.mjs`.

## Licenze

- DeepSeek Harness: MIT, © 2026 DeepSeek ([LICENSE-DeepSeek-Harness.txt](LICENSE-DeepSeek-Harness.txt)).
  "DeepSeek Harness" è un marchio di DeepSeek ed è citato solo per indicare su cosa si basa questo
  componente. I dizionari italiani sono traduzioni dei testi originali MIT.
- Lexend: SIL Open Font License 1.1 ([plugins/dsh-workspace-brand/OFL-Lexend.txt](plugins/dsh-workspace-brand/OFL-Lexend.txt)).
- Logo, icona e linee guida Workspace: proprietà di Workspace S.r.l.
- Plugin e script Workspace in questa cartella: MIT.
