# FEEDBACK QA – ciclo 8

**Ambito:** l'ultima PR aperta, cioè la #21 (`claude/workspace-os-installer` → `main`; la #20 punta allo stesso branch), commit `ddfb549` "fix: correzioni QA ciclo 7 (Bug #28-30; Mgl #18-20)". Ho verificato tutte le voci ancora aperte e le prove su Windows pubblicate dal responsabile nel commento 6302773000 sulla PR #21 (20/10/2026, 23:00–23:45, Windows 11, PowerShell 5.1, Ollama e LM Studio 0.4.25).

**Esito:** NON APPROVATO, per poco.
- **Chiuse:**
  - Bug #26 e #27, grazie alle prove reali su Windows;
  - Bug #28, #29 e #30;
  - Miglioramenti #19 e #20.
- **Ancora aperto:** il Miglioramento #18. La prova su LM Studio 0.4.25 aveva mostrato che la versione precedente non funzionava; quella nuova (`instance_id`) va riprovata dal vivo.
- **Nuove:**
  - Bug #31 (bassa, sicurezza): 4 aggiramenti residui del filtro PowerShell;
  - Miglioramenti #21 e #22.

**Test eseguiti (Linux, 21/10/2026 03:00):**
- **Motore:** `uv run pytest`: 178 passati, 1 saltato, 1 fallito. Il test fallito è `test_mcp.py::test_stdio_server_lifecycle_and_secrets` (DPAPI, solo Windows): è atteso.
- **`ruff 0.15.20`**, `ruff check vault_engine tests` → `All checks passed!`, codice d'uscita 0.
- **Interfaccia:** `npm ci` e `npm run build` vanno a buon fine; `node --test electron/openable.test.cjs` → 6 su 6.
- **Workspace Harness:** `npm ci` e `npm test` superano 7 controlli su 7, compreso quello nuovo sul BOM. Il controllo sui junction gira solo su Windows.
- **BOM:** tutti e 5 i file `*.ps1` iniziano con `EF BB BF`.
- **Bug #29 dal vivo dietro il proxy di questo ambiente:** `fetch_url` scarica `https://example.com/` e `https://www.python.org/`.
- **Sonde:** quelle del ciclo 7 non trovano più i difetti (8 su 8), e i controlli positivi passano. Quelle del ciclo 8 confermano 4 aggiramenti (Bug #31).

---

## Segnalazione dal PC del responsabile (21/10/2026) – da correggere prima del ciclo 9

Installazione reale su Windows: un Vault di 272 file (8.433 chunk, 281 pagine OCR, 186,9 MB), con chunking ricorsivo 1000/150, metrica cosine e **riassunto contestuale** attivo, mostra **23 errori**. Esempio:

```
C:\Users\Antonio Cavalli\OneDrive\Antiriciclaggio\Posizioni Aperte\0006 Wallace Trust\20260310-1988-amendments.pdf
SHA-256 148b9ccabcd1a5cdd58dced37f00308fdcfbd29dac7a03bfdc7f6676d12bd49e · Indicizzato 21/10/2026 10:20:18
Note: riassunto contestuale: chat qwen3:4b-instruct: HTTP 400: request (4236 tokens) exceeds the available context size (4096 tokens), try increasing it
```

- [ ] **Bug #32 (alta): il riassunto contestuale supera il contesto di 4.096 token del modello Ollama installato dall'installatore**
  - **File:**
    - `engine/vault_engine/pipeline.py` (`SUMMARY_PROMPT`, `SUMMARY_INPUT_CHARS = 12000`, `prepare_file`);
    - `engine/vault_engine/providers.py` (`ProviderClient.chat`);
    - `installer/installa.ps1` e `installer/ollama.ps1` (LLM predefinito `qwen3:4b-instruct`).
  - **Causa:**
    - Il riassunto invia al modello i primi **12.000 caratteri** del documento, più il prompt, e chiede fino a 300 token di risposta.
    - Con testi legali, numeri e OCR siamo intorno a 2,8–3 caratteri per token, quindi la richiesta arriva a circa **4.200–4.300 token**: il caso reale ne conta 4.236.
    - L'installatore configura come LLM dell'app `qwen3:4b-instruct`, che Ollama carica con il contesto predefinito di **4.096** token.
    - La chiamata passa da `/v1/chat/completions` (API compatibile OpenAI), che **non** permette di passare `num_ctx`. L'unico modello con contesto ampio, `workspace-agent` (16.384), viene creato solo per la Harness.
  - **Effetti:** i documenti lunghi e densi (contratti, atti, PDF scansionati) falliscono. I file brevi passano, per questo gli errori sono 23 su 272 e non tutti.
  - **Come riprodurlo:**
    - Vault con riassunto contestuale attivo e LLM `ollama/qwen3:4b-instruct` (configurazione dell'installatore): un PDF con più di circa 11.000 caratteri di testo fitto va in errore con il messaggio sopra;
    - sonda `test_summary_input_exceeds_4096_token_context`.
  - **Correzione proposta** (anche combinate):
    1. per Ollama usare l'API nativa `/api/chat` con `options.num_ctx` (es. 8.192), come fa già `ensure_loaded` per `keep_alive`;
    2. calcolare la lunghezza del testo in base al contesto reale del modello (`/api/show` → `num_ctx`, `/api/ps` → `context_length`; LM Studio → `loaded_context_length`), lasciando margine per prompt e risposta. Con 4.096 token restano circa 8.000 caratteri;
    3. sull'errore "exceeds the available context size", riprovare una volta con metà del testo;
    4. nell'installatore impostare come LLM dell'app `workspace-agent` quando esiste, oppure creare un modello con contesto ampio anche per l'app.

- [ ] **Bug #33 (media): se il riassunto contestuale fallisce, l'intero documento resta fuori dal Vault**
  - **File:** `engine/vault_engine/pipeline.py` (`prepare_file`, ramo `except` del riassunto).
  - **Causa:** l'errore del riassunto, che è solo un arricchimento facoltativo, finisce in `_record_error`. Lo stato diventa `error`, i chunk del file vengono **cancellati** e il documento non viene indicizzato affatto.
  - **Effetti:** i 23 documenti, tra cui atti della posizione "0006 Wallace Trust", **non sono ricercabili**, né dalla ricerca né dall'agente, anche se il testo è stato estratto correttamente (OCR compreso).
  - **Come riprodurlo:** sonda `test_summary_failure_drops_whole_document`. Con `ProviderClient.chat` che solleva l'errore di contesto, il file risulta `error` e il Vault ha 0 chunk.
  - **Correzione proposta:**
    - in caso di errore del riassunto, proseguire **senza** riassunto (`summary=None`);
    - indicizzare il documento con stato `indexed`, mettendo un avviso nel campo note (es. "indicizzato senza riassunto contestuale: …");
    - lasciare `error` solo per i difetti di lettura o parsing.

- [ ] **Miglioramento #23: avvisare quando l'LLM scelto ha poco contesto per il riassunto contestuale**
  - **File:** `desktop/src/pages/Settings.tsx` e la pagina del Vault (opzione "Contestuale").
  - **Proposta:**
    - all'attivazione del riassunto contestuale, o alla scelta dell'LLM, mostrare il contesto del modello letto da Ollama o LM Studio;
    - avvisare sotto gli 8.192 token, come già fa la Harness con la soglia dei 12.000.

**Rimedio immediato per l'utente, in attesa della correzione** (poi "Sincronizza": i file in errore vengono rielaborati):
- in Impostazioni scegli come LLM `workspace-agent`, se la Harness è installata (contesto 16.384);
- oppure imposta `OLLAMA_CONTEXT_LENGTH=8192` (o `16384`) nelle variabili d'ambiente dell'utente e riavvia Ollama. Più contesto significa più RAM/VRAM.

<details><summary>Codice delle sonde (salvarlo in <code>engine/tests/_probe_qa9.py</code>, file temporaneo)</summary>

```python
"""Sonde segnalazione 21/10 (riassunto contestuale): PASSANO se il difetto è presente."""
import asyncio

from vault_engine import pipeline
from vault_engine.config import ModelRef, SettingsStore
from vault_engine.events import EventBus
from vault_engine.providers import ProviderError
from vault_engine.vaults import VaultConfig, VaultRegistry


def test_summary_input_exceeds_4096_token_context():
    # 12.000 caratteri di testo legale/numerico ≈ 2,8-3 caratteri per token → ~4.000-4.300 token,
    # più prompt e max_tokens=300: oltre i 4.096 del contesto predefinito di Ollama.
    budget_tokens = pipeline.SUMMARY_INPUT_CHARS / 2.9 + len(pipeline.SUMMARY_PROMPT) / 4 + 300
    assert budget_tokens > 4096


def test_summary_failure_drops_whole_document(tmp_path, monkeypatch, fake_embeddings):
    monkeypatch.setenv("WSOS_DATA_DIR", str(tmp_path / "data"))
    src = tmp_path / "src"
    src.mkdir()
    (src / "contratto.txt").write_text("Contratto di trust Wallace, emendamenti 1988. " * 50)

    async def too_long(self, *a, **k):
        raise ProviderError("chat qwen3:4b-instruct: HTTP 400: request (4236 tokens) exceeds the available context size (4096 tokens)")
    monkeypatch.setattr(pipeline.ProviderClient, "chat", too_long)

    async def scenario():
        events = EventBus(); events.bind(asyncio.get_running_loop())
        settings = SettingsStore()
        settings.update({"llm": {"provider": "ollama", "model": "qwen3:4b-instruct"}})
        registry = VaultRegistry()
        jobs = pipeline.JobManager(registry, settings, events)
        vault = registry.create(VaultConfig(name="T", sources=[str(src)], embedding=ModelRef(provider="lmstudio", model="fake"), contextual_summary=True))
        job = jobs.submit(vault.config.id, "sync")
        while job.status in ("queued", "running"):
            await asyncio.sleep(0.05)
        await jobs.shutdown()
        return vault
    vault = asyncio.run(scenario())
    rec = vault.file(str(src / "contratto.txt"))
    # il documento è in errore e NON ha chunk: non è ricercabile affatto
    assert rec.status == "error" and "riassunto contestuale" in rec.error
    assert vault.count_chunks() == 0
```

</details>

---

## Ciclo 8 – Bug

- [x] **Bug #31 (bassa, sicurezza): il filtro su `-EncodedCommand` si aggira ancora con accento grave, operatore punto e `$env:ComSpec`**
  - **Soluzione applicata (ciclo 8):** in `engine/vault_engine/agent/tools.py`: nuova `_deobfuscate_backticks` chiamata all'ingresso di `_uses_encoded_command` (vale anche per le righe annidate riesaminate): le sequenze reali `` `n `` `` `t `` `` `r `` `` `0 `` `` `a `` `` `b `` `` `f `` `` `v `` diventano il carattere di controllo (così `` -e`nc `` si spezza in `-e` + `nc`), l'accento grave a fine riga unisce le righe e ogni altro `` ` `` viene tolto (`power`shell` → `powershell`); l'operatore `.` in testa al segmento è trattato come `&`; `$env:ComSpec` (anche `${env:ComSpec}`) è riconosciuto come `cmd` nella scansione di `/c` e `/k`. I 4 casi della sonda sono bloccati; nessun nuovo falso positivo sui comandi legittimi. Test: `engine/tests/test_regressions_qa_ciclo8.py` (`test_encoded_filter_bypass_cycle8_blocked`, 5 casi; `test_encoded_filter_cycle8_no_false_positives`, 5 casi).
  - **File:** `engine/vault_engine/agent/tools.py` (`_uses_encoded_command`, `_segment_tokens`).
  - **Causa:**
    - il nome del comando e gli switch vengono confrontati così come sono scritti;
    - ma PowerShell ignora l'accento grave (`` ` ``) davanti a una lettera senza significato speciale, una tecnica di offuscamento nota;
    - l'operatore `.` (dot-source) avvia un programma come `&`;
    - `cmd` può essere richiamato tramite `$env:ComSpec`.
  - **Comandi codificati che passano il filtro** (sonda `test_encoded_filter_bypass_cycle8`):
    - ``power`shell -e <b64>``
    - ``powershell -e`nc <b64>``
    - `. powershell -e <b64>`
    - `& $env:ComSpec /c powershell -e <b64>`
  - **Rischio:** basso. Il filtro è dichiaratamente una protezione aggiuntiva, non un isolamento, e ogni comando passa dalla scheda di approvazione dell'utente. Ma sono le stesse tecniche usate dagli strumenti di offuscamento.
  - **Correzione proposta:**
    - prima di dividere in token, togliere gli accenti gravi non seguiti da `n`, `t`, `r`, `0`, `a`, `b`, `f`, `v` o da un a capo;
    - trattare `.` in testa come `&`;
    - riconoscere `$env:ComSpec` come `cmd`;
    - aggiungere i 4 casi alle regressioni.

---

## Ciclo 8 – Miglioramenti

- [x] **Miglioramento #21 (Workspace Harness): ricarico in LM Studio più robusto (casi limite del Miglioramento #18)**
  - **Soluzione applicata (ciclo 8):** in `harness/avvia.ps1` (blocco LM Studio): lo scarico ora riguarda **tutte** le `loaded_instances` del modello (un `unload` per ogni `instance_id`; ripiego su `{"model": …}` solo se l'API v1 non è disponibile) e basta un solo scarico fallito per saltare il caricamento con avviso. Dopo il `load` lo script rilegge `/api/v1/models` e avvisa se il modello non ha esattamente **una** istanza con contesto di almeno 16.384 token (leggendo `config.context_length` dell'istanza), indicando il rimedio manuale; in quel caso il `contextWindow` registrato viene aggiornato al valore reale invece che a 16.384. Sintassi verificata con il parser di PowerShell; **da riprovare dal vivo su LM Studio 0.4.x** (stessa sessione della prova del Miglioramento #18).
  - **File:** `harness/avvia.ps1` (blocco LM Studio).
  - **Problema:**
    - viene scaricata solo `loaded_instances[0]`: se sono rimaste più istanze dello stesso modello (per esempio una `modello:2` lasciata da un avvio precedente), le altre restano in memoria e le richieste per `modello` possono finire su quella a contesto piccolo;
    - dopo il `load` nessuno controlla l'esito reale.
  - **Proposta:**
    - scaricare **tutte** le `loaded_instances` del modello;
    - dopo il caricamento rileggere `/api/v1/models` e avvisare se le istanze non sono esattamente una, con contesto di almeno 16.384.

- [x] **Miglioramento #22 (Workspace Harness): il contesto impostato nell'app Ollama non viene letto**
  - **Soluzione applicata (ciclo 8):** in `harness/avvia.ps1` (blocco Ollama): quando ci sono modelli «Non offerti all'agente» e **non** è impostata `OLLAMA_CONTEXT_LENGTH`, compare una riga aggiuntiva: «Se hai impostato un contesto più ampio nelle Impostazioni dell'app Ollama, imposta anche la variabile OLLAMA_CONTEXT_LENGTH oppure rilancia INSTALLA.bat per creare workspace-agent: quel valore non è leggibile dalla Harness.» Documentato in `harness/README.md` (nuovo paragrafo «Contesto di Ollama» nella sezione Modelli locali, con la nota che il server legge le variabili solo al proprio avvio). Non implementata la lettura del contesto reale via `POST /api/generate` + `/api/ps` (opzione «in alternativa»): un caricamento, anche leggero, occupa RAM/VRAM a ogni avvio; il messaggio copre il caso senza effetti collaterali.
  - **File:** `harness/avvia.ps1` (blocco Ollama) e `harness/README.md`.
  - **Problema:** caso limite segnalato al ciclo 7 e confermato nella prova su Windows. Se il contesto è impostato dalle Impostazioni dell'app Ollama invece che con `OLLAMA_CONTEXT_LENGTH`, i modelli non caricati vengono considerati a 4.096 token e nascosti all'agente.
  - **Proposta:**
    - nel messaggio "Non offerti all'agente…" aggiungere come rimedio `OLLAMA_CONTEXT_LENGTH` o `workspace-agent`;
    - documentarlo nel README;
    - in alternativa, per il modello predefinito, leggere il contesto reale con un caricamento leggero (`POST /api/generate` senza prompt) seguito da `/api/ps`.

---

## Prova da eseguire su Windows (Miglioramento #18)

Come al ciclo 7, con LM Studio 0.4.x e Ollama chiuso:
1. In LM Studio carica il modello scelto con contesto 4.096 (`lms load <id> --context-length 4096`) e assicurati che ci sia **una sola** istanza (`lms ps`).
2. Avvia la Harness dal menu Start. **Atteso:** compare il messaggio "Carico <id> in LM Studio con un contesto di 16384 token…".
3. Esegui `lms ps` e `(Invoke-RestMethod http://127.0.0.1:1234/api/v1/models).models | ? key -eq '<id>' | % { $_.loaded_instances } | Select id, config`. **Atteso:** una sola istanza, con 16.384 token di contesto, e nessuna `<id>:2`.
4. **Prova dell'errore:** blocca lo scarico, per esempio con `lms load <id>` aperto da un'altra sessione che lo tiene occupato, oppure simulando un `instance_id` errato. **Atteso:** l'avviso "Scarico di <id> non riuscito: salto il caricamento…" e nessuna seconda istanza.

---

## Verifica delle voci del ciclo 7

### Bug

- [x] **Bug #28 (media, sicurezza, in parte regressione): il filtro su `-EncodedCommand` guarda solo il primo token di ogni comando e si aggira con blocchi e sottoespressioni**
  - **Verifica QA ciclo 8:** Verificato: le 7 forme del ciclo 7 e il caso di regressione ora sono bloccate (8 sonde su 8 falliscono), e i comandi legittimi provati restano permessi. Restano 4 aggiramenti meno evidenti: vedi Bug #31.
  - **File:** `engine/vault_engine/agent/tools.py` (`_uses_encoded_command`, `_segment_tokens`).
  - **Causa:**
    - per correggere il Bug #17, `powershell`/`pwsh` vengono riconosciuti solo come **primo token** di un segmento (dopo `;`, `|`, `&`, `&&` o `||`);
    - ma in PowerShell un comando può iniziare anche dopo `(`, `$(` e `{`, e dentro `if`, `try`, `ForEach-Object` e simili;
    - inoltre `&"C:\…\pwsh.exe"`, cioè `&` attaccato al percorso tra virgolette, viene spezzato da `_TOKEN` in `&"C:\Program` + `Files\…pwsh.exe"`;
    - e l'alias `saps` di `Start-Process` non è nell'elenco.
  - **Comandi codificati che passano il filtro** (sonda `test_encoded_filter_bypass_cycle7`):
    - `(powershell -e <b64>)`
    - `$(powershell -e <b64>)`
    - `if ($true) { powershell -e <b64> }`
    - `1 | ForEach-Object { powershell -e <b64> }`
    - `try { pwsh -enc <b64> } catch { }`
    - `&"C:\Program Files\PowerShell\7\pwsh.exe" -enc <b64>`
    - `saps powershell -ArgumentList '-e <b64>'`
  - **Regressione:** la versione del ciclo 6 (`0d74647`) bloccava `if (…) { powershell -e … }` e `… | ForEach-Object { powershell -e … }`, quella attuale no. Ho controllato caricando entrambe le versioni.
  - **Correzione proposta:**
    - considerare inizio di comando anche ciò che segue `(`, `$(`, `{` e `}`: separarli come i separatori, oppure togliere `({$` dall'inizio del token di testa;
    - riconoscere come testa anche il primo token dopo le parole chiave `if`, `elseif`, `else`, `try`, `catch`, `finally`, `foreach` e `while`;
    - unire `&` attaccato a un token tra virgolette;
    - aggiungere `saps` a `_LAUNCHER_NAMES`;
    - aggiungere i 7 casi alle regressioni.

- [x] **Bug #29 (media, regressione del Miglioramento #16): dietro un proxy `fetch_url` non riesce più a scaricare nessuna pagina HTTPS**
  - **Verifica QA ciclo 8:** Verificato dal vivo dietro il proxy di questo ambiente: `fetch_url("https://example.com/")` → OK "Example Domain", `fetch_url("https://www.python.org/")` → OK. Con un proxy attivo la richiesta va per nome host (`_proxy_for`), senza proxy resta il pinning.
  - **File:** `engine/vault_engine/agent/web.py` (`_pinned_target`, `fetch_url`).
  - **Causa:**
    - la richiesta viene ora inviata all'**IP** validato (`https://104.20.23.154/`) con `Host`/SNI originali;
    - se è configurato un proxy, httpx gli chiede `CONNECT 104.20.23.154:443`, e molti proxy aziendali filtrano per nome e rifiutano le connessioni per IP;
    - httpx usa il proxy delle variabili `HTTPS_PROXY`/`HTTP_PROXY` e, su Windows, anche quello di sistema (letto dal registro tramite `urllib.request.getproxies()`).
    - Con un proxy in mezzo il pinning è comunque inutile, perché la risoluzione DNS la fa il proxy.
  - **Come riprodurlo** (in questo ambiente c'è un proxy HTTPS):
    - `fetch_url("https://example.com/")` con `1022a7c` → `WebError: download non riuscito: ConnectError`;
    - con `web.py` di `0d74647` → OK ("Example Domain");
    - isolato con httpx e proxy attivo:
      - `GET https://104.20.23.154/` + `Host: example.com` + `sni_hostname` → `ConnectError [Errno 104] Connection reset by peer`;
      - `GET https://example.com/` → 200.
  - **Non verificato qui:** il pinning senza proxy. In questo ambiente il traffico TLS è ispezionato, quindi la connessione diretta fallisce comunque per il certificato, anche per nome.
  - **Correzione proposta:**
    - se per l'URL è attivo un proxy (`httpx._utils.get_environment_proxies()` / `urllib.request.getproxies()` più `proxy_bypass`), non fissare l'IP e inviare il nome host: la protezione SSRF resta sul controllo iniziale e sui redirect;
    - aggiungere un test con un proxy finto che verifichi che la richiesta `CONNECT` usa il nome host.

- [x] **Bug #30 (bassa, regressione): `harness/avvia.ps1` ha perso il BOM UTF-8, quindi in Windows PowerShell 5.1 i messaggi in italiano sono storpiati**
  - **Verifica QA ciclo 8:** Verificato: tutti e 5 gli script `*.ps1` (`harness/avvia.ps1`, `harness/tools/collegamenti.ps1`, `harness/tools/testa-junction.ps1`, `installer/installa.ps1`, `installer/ollama.ps1`) iniziano con `ef bb bf`, e `npm test` della Harness ha l'8° controllo "script .ps1 con BOM UTF-8" che passa. Il difetto era stato confermato dal vivo su Windows nel commento 6302773000.
  - **File:** `harness/avvia.ps1`; anche `harness/tools/testa-junction.ps1`, nuovo, è senza BOM.
  - **Causa:**
    - `1022a7c` ha tolto i 3 byte `EF BB BF` iniziali (con `0d74647` il file inizia con `ef bb bf`, ora con `23 20 41`);
    - il collegamento del menu Start lancia `powershell.exe` 5.1, che senza BOM legge il file come ANSI (Windows-1252).
  - **Effetti:** tutti i messaggi con lettere accentate escono storpiati: `DeepSeek Harness non Ã¨ installato`, `Workspace Harness Ã¨ pronto`, `potrÃ `, `puÃ²`, `Ã¨ giÃ  in uso` (righe 36, 38, 143, 164, 213, 218, 225, 226). Non ho trovato sequenze che diventino virgolette tipografiche nel codice, quindi l'analisi dello script non dovrebbe rompersi.
  - **Come riprodurlo:** su Windows 11 lancia il collegamento "Workspace Harness" con Node/dsh assenti, oppure leggi i messaggi di avvio.
  - **Correzione proposta:**
    - salvare entrambi i file in UTF-8 **con BOM**, come `installer/*.ps1`;
    - aggiungere a `harness/tools/test.mjs` un controllo che ogni `*.ps1` del repository inizi con `EF BB BF` (`.gitattributes` gestisce già i fine riga CRLF, ma non il BOM).

---

### Miglioramenti

- [x] **Miglioramento #19: `testa-junction.ps1` prova una copia della logica, non `avvia.ps1`, e non copre il collegamento orfano**
  - **Verifica QA ciclo 8:** Verificato nel codice: `harness/tools/collegamenti.ps1` (`Installa-PluginWorkspace`) è richiamato sia da `avvia.ps1` sia da `testa-junction.ps1`, che ora copre il caso orfano con A ancora assente (righe 30–34). L'esecuzione 5/5 su Windows è dichiarata dallo sviluppatore; qui non è eseguibile.
  - **File:** `harness/tools/testa-junction.ps1`.
  - **Problema:**
    - la funzione `Collega` è una copia del blocco di `avvia.ps1`: se uno dei due cambia, il test continua a passare;
    - nel caso 2 la cartella A viene ripristinata **prima** di `Collega`, quindi il percorso "collegamento orfano → `Directory.Delete` → nuovo collegamento verso un'altra destinazione" (il passo 2 originale del Bug #26) non viene mai eseguito.
  - **Proposta:**
    - spostare la logica in `harness/tools/collegamenti.ps1` e richiamarla da `avvia.ps1` e dal test;
    - aggiungere il caso: collegamento orfano verso `A-spostata`, poi `Collega` verso `B` mentre A è ancora assente.

- [x] **Miglioramento #20: `fetch_url` prova solo il primo IP validato**
  - **Verifica QA ciclo 8:** Verificato nel codice e con il test `test_fetch_url_tries_next_validated_ip_on_connect_error`: al `ConnectError` si passa all'IP validato successivo; dopo l'ultimo l'errore si propaga.
  - **File:** `engine/vault_engine/agent/web.py`.
  - **Problema:** `_pinned_target(current, ips[0])` usa solo il primo indirizzo. Se è IPv6 e la rete ha solo IPv4, o se quell'IP non risponde, il download fallisce, mentre httpx per nome proverebbe anche gli altri.
  - **Proposta:** in caso di `ConnectError` provare in ordine tutti gli IP già validati.

---

## Verifica delle voci del ciclo 6

### Bug

- [x] **Bug #26 (media, Workspace Harness, da confermare su Windows): un collegamento ai plugin rimasto orfano blocca l'avvio, e la sua rimozione può cancellare i file di un'altra copia**
  - **Verifica QA ciclo 8:** Verificato tramite la prova su Windows 11 / PowerShell 5.1 del responsabile (commento 6302773000 sulla PR #21, 20/10 ore 23:00), eseguita con i passi originali. Avvio da B con il collegamento orfano: OK (prima la finestra si chiudeva). `C:\Prove\A\harness\plugins`: 76 file prima e dopo, intatti. Il codice è ora in `collegamenti.ps1` (Miglioramento #19). Non l'ho eseguita io: qui non c'è PowerShell.
  - **Verifica QA ciclo 7:** Da confermare su Windows. Nel codice la correzione è corretta: `Get-Item -LiteralPath` non segue il collegamento, la rimozione usa `[System.IO.Directory]::Delete` senza ricorsione, e il confronto avviene su `GetFullPath`. Però qui non c'è PowerShell e non ho potuto eseguire i passi originali. Inoltre `testa-junction.ps1` non copre lo scenario 2 originale: nel caso 2 la cartella A viene rinominata di nuovo **prima** di chiamare `Collega`, quindi il collegamento orfano non viene mai sostituito mentre è orfano (vedi Miglioramento #19). Procedura in «Prove da eseguire su Windows».
  - **File:** `harness/avvia.ps1` (ciclo `foreach ($p in 'dsh-workspace-brand', 'dsh-workspace-it')`).
  - **Causa:**
    - Lo script usa `Test-Path $link` per capire se il collegamento esiste. Per un collegamento orfano (cartella di destinazione spostata o cancellata, per esempio dopo aver spostato o riclonato `WorkspaceOS`) `Test-Path` segue il collegamento e restituisce `$false`.
    - Il successivo `New-Item -ItemType Junction` fallisce perché il nome esiste già. Con `$ErrorActionPreference = 'Stop'` lo script si chiude a ogni avvio, finché l'utente non cancella il collegamento a mano.
    - Se invece il collegamento punta a un'**altra** copia ancora esistente (due cloni usati in alternanza), lo script esegue `Remove-Item $link -Recurse -Force`. In Windows PowerShell 5.1 questo comando, su un collegamento di tipo junction, cancella il **contenuto della cartella di destinazione** (problema noto, corretto solo da PowerShell 6). Si perderebbero così i file di `plugins\dsh-workspace-*` dell'altra copia.
  - **Come riprodurlo (Windows 11, PowerShell 5.1):**
    1. Avvia una volta la Harness da una copia A del progetto, poi rinomina la cartella di A: il collegamento in `%LOCALAPPDATA%\WorkspaceOS\harness\profiles\workspace\node_modules\@workspace-sm\dsh-workspace-brand` resta orfano.
    2. Avvia da una copia B: la finestra si chiude con un errore di `New-Item`.
    3. Rinomina A al suo nome originale, avvia da A e poi da B: dopo l'avvio da B controlla `A\harness\plugins\dsh-workspace-brand`.
  - **Correzione proposta:**
    - verificare l'esistenza con `Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue`, che non segue il collegamento, invece di `Test-Path`;
    - togliere il collegamento senza toccare la destinazione: `[System.IO.Directory]::Delete($link)` (senza ricorsione) oppure `cmd /c rmdir "$link"`, **mai** `Remove-Item -Recurse` su un collegamento;
    - confrontare il `Target` con `[IO.Path]::GetFullPath(...)` per evitare differenze di forma del percorso.

- [x] **Bug #27 (bassa, Workspace Harness): un modello Ollama senza `num_ctx` viene sempre considerato a 4.096 token e nascosto all'agente**
  - **Verifica QA ciclo 8:** Verificato tramite la prova su Windows con Ollama reale del responsabile (commento 6302773000). Con `OLLAMA_CONTEXT_LENGTH=32768` il modello `qwen3:4b-instruct` viene offerto e `/api/ps` riporta `context_length: 32768`; senza la variabile torna tra i "Non offerti". L'hash di `cordis.patch.yml` è identico prima e dopo (`E47ABA48…683BC`). Il caso limite delle Impostazioni dell'app Ollama resta, come documentato: vedi Miglioramento #22.
  - **Verifica QA ciclo 7:** Da confermare su Windows con Ollama reale. Nel codice: precedenza `/api/ps` (`context_length`) → `num_ctx` → `OLLAMA_CONTEXT_LENGTH` (utente, poi macchina) → 4.096, e `cordis.patch.yml` non viene più riscritto (solo un avviso). Casi limite rimasti: il contesto impostato dalle Impostazioni dell'app Ollama, che non è una variabile d'ambiente, non viene letto; una variabile impostata senza riavviare Ollama fa offrire un modello che il server carica ancora a 4.096. Procedura in «Prove da eseguire su Windows».
  - **File:** `harness/avvia.ps1` (blocco Ollama, `b527423`).
  - **Causa:**
    - `$ctx = 4096` vale per ogni modello che non ha `num_ctx` nei `parameters` del Modelfile;
    - ma il contesto effettivo dipende anche dal server: per esempio con la variabile `OLLAMA_CONTEXT_LENGTH` (o dalle impostazioni dell'app Ollama) tutti i modelli vengono caricati con 32.768 token;
    - dopo `b527423` questi modelli vengono **nascosti** (`$ctx -lt 12000`);
    - se è stato scelto nelle Impostazioni, `cordis.patch.yml` viene riscritto sostituendolo con `workspace-agent`.
  - **Effetti:** chi ha configurato Ollama con un contesto ampio a livello di server si ritrova con l'elenco dei modelli ridotto al solo `workspace-agent`, o vuoto se non esiste, e la propria scelta viene cambiata in silenzio.
  - **Come riprodurlo:**
    1. Imposta `OLLAMA_CONTEXT_LENGTH=32768` e riavvia Ollama.
    2. Avvia la Harness: `qwen3:4b-instruct` compare tra i "Non offerti all'agente (contesto sotto 12.000 token)".
  - **Correzione proposta:**
    - leggere anche `OLLAMA_CONTEXT_LENGTH` dall'ambiente utente/macchina, oppure, per i modelli già caricati, `context_length` di `/api/ps`;
    - non riscrivere il file dell'utente, ma mostrare l'avviso e lasciare la scelta.

---

### Miglioramenti

- [ ] **Miglioramento #18 (Workspace Harness, da verificare): caricamento in LM Studio di un modello già in memoria con contesto piccolo**
  - **Verifica QA ciclo 8:** Ancora da confermare su Windows. La prova del 20/10 su LM Studio 0.4.25 ha mostrato che la versione precedente **non** funzionava: `unload {"model"}` → 400 `Missing required field 'instance_id'`, e si creava la seconda istanza `qwen3.6-35b-a3b:2`. `ddfb549` usa ora `instance_id` (da `/api/v1/models` → `loaded_instances[0].id`), ripiega su `{model}` e, se lo scarico fallisce, avvisa e non carica. Nel codice la logica è corretta, ma la nuova versione non è ancora stata provata dal vivo: va ripetuta la procedura qui sotto. Restano due casi limite: vedi Miglioramento #21.
  - **Verifica QA ciclo 7:** Da confermare su Windows con LM Studio reale. Nel codice `unload` viene chiamato prima di `load`, ma con il corpo `{"model": id}` e l'errore scartato da `catch { }`. Se la versione installata di LM Studio richiede `instance_id` per lo scarico, la chiamata fallisce senza alcun segnale e si torna alla doppia istanza. Procedura in «Prove da eseguire su Windows».
  - **File:** `harness/avvia.ps1` (blocco LM Studio).
  - **Problema:**
    - Se il modello scelto è già caricato con meno di 12.000 token, lo script chiama `POST /api/v1/models/load` con `context_length: 16384` senza prima scaricarlo dalla memoria.
    - A seconda della versione, LM Studio può creare una **seconda istanza** (identificativo `modello:2`, il doppio della RAM/VRAM) e continuare a instradare le richieste per `modello` alla prima, ancora a contesto piccolo.
  - **Proposta:**
    - se il modello è `loaded` con contesto insufficiente, scaricarlo prima (`POST /api/v1/models/unload`) e poi ricaricarlo;
    - oppure usare l'identificativo dell'istanza restituito dal caricamento come `id` della rotta per dsh;
    - verificare con LM Studio 0.3.x il comportamento reale.

---

## Verifica delle voci del ciclo 5

### Bug

- [x] **Bug #19 (alta): "Elimina" nella pagina Modelli fallisce sempre con un errore 500**
  - **Verifica QA ciclo 6:** Verificato: `delete` usa `client.request("DELETE", …, json=…)`. Le sonde del ciclo 5 ora falliscono e `test_regressions_qa_ciclo5.py` controlla metodo, percorso e body con `httpx.MockTransport`, senza sostituire `ollama_hub.delete`.
  - **File:** `engine/vault_engine/ollama_hub.py` (`delete`) e `engine/vault_engine/app.py` (`ollama_delete`).
  - **Causa:** `client.delete(f"{base}/api/delete", json={"model": model})`. In httpx 0.28.1 (versione installata) `AsyncClient.delete()` **non ha** il parametro `json` (firma: `url, params, headers, cookies, auth, follow_redirects, timeout, extensions`). Ne risulta `TypeError: AsyncClient.delete() got an unexpected keyword argument 'json'` ancora prima di contattare Ollama.
  - **Effetti:**
    - `/ollama/delete` cattura solo `HubError`, quindi risponde **500** e la pagina Modelli mostra un errore generico.
    - Il modello però viene prima scaricato dalla memoria (`unload`), quindi l'utente vede sparire il modello dalla RAM ma non dal disco.
    - Nessun test se ne accorge: tutti sostituiscono `ollama_hub.delete` con un finto (`test_regressions_qa_ciclo2.py`). La nota del ciclo 2 "verificato live" non è riproducibile con httpx 0.28.
  - **Come riprodurlo:**
    - pagina Modelli → "Elimina" su un modello installato → conferma → errore;
    - oppure `asyncio.run(ollama_hub.delete({"ollama": "http://127.0.0.1:11434"}, "x:latest"))` → `TypeError`;
    - sonde: `test_hub_delete_raises_typeerror`, `test_delete_route_answers_500`.
  - **Correzione proposta:**
    - `await client.request("DELETE", f"{base}/api/delete", json={"model": model})`;
    - aggiungere un test con `httpx.MockTransport` che verifichi metodo, percorso e body della richiesta senza sostituire `ollama_hub.delete`.

- [x] **Bug #20 (media): l'avanzamento dei download avviati automaticamente non compare da nessuna parte**
  - **Verifica QA ciclo 6:** Verificato nel codice: `pulls` è indicizzato con `normalizeName` e la sezione "Download in corso" mostra i download che non corrispondono a nessuna riga. `tsc` e la build passano.
  - **File:** `desktop/src/pages/Models.tsx` (`pulls`, `progressOf`).
  - **Causa:**
    - lo stato dei download è indicizzato con il nome **esatto** ricevuto negli eventi;
    - le righe della pagina lo cercano con il proprio nome: quello installato (`bge-m3:latest`) o quello della libreria, senza tag (`qwen3`);
    - un download avviato da un Vault, da una ricerca o dall'agente usa il nome delle impostazioni (es. `qwen3:4b-instruct`, `bge-m3:latest`, che l'installatore ora scrive con il tag).
  - **Effetti:**
    - per un modello non ancora installato e non presente tra i risultati della libreria non esiste nessuna riga: l'avanzamento e l'eventuale errore con "Riprova" (Bug #2 e #9) non si vedono;
    - con un nome che ha il tag, la riga della libreria (senza tag) non trova l'evento.
  - **Come riprodurlo:**
    - Vault con embedding `ollama/nomic-embed-text:v1.5`, non installato;
    - avvia la sincronizzazione e apri Modelli: nessuna riga mostra il download, anche se gli eventi `pull` arrivano (visibili in `/events`).
  - **Correzione proposta:**
    - indicizzare `pulls` con `normalizeName(e.model)` e cercare con `normalizeName(riga)`;
    - aggiungere una sezione "Download in corso" che elenchi le voci di `pulls` non mostrate da nessuna riga, con avanzamento, errore e "Riprova".

- [x] **Bug #21 (bassa): un errore immediato del download può essere sovrascritto e la riga resta su "download_avviato…" senza "Riprova"**
  - **Verifica QA ciclo 6:** Verificato nel codice: lo stato "in avvio" viene impostato prima della richiesta, e la risposta lo sostituisce solo se nel frattempo non è arrivato un evento (confronto per identità con `starting`).
  - **File:** `desktop/src/pages/Models.tsx` (`pull`).
  - **Causa:**
    - `setPulls(... status: "download_avviato")` viene eseguito **dopo** `await api.ollamaPull(model)`;
    - la risposta 202 e gli eventi SSE viaggiano su connessioni diverse;
    - se il download fallisce subito, l'evento `errore` (o `download_completato`) può arrivare prima della risposta e viene sovrascritto.
  - **Come riprodurlo:**
    - Ollama spento, pagina Modelli, cerca in libreria e premi "Scarica";
    - il task in background fallisce subito con "Ollama non raggiungibile": a seconda dell'ordine di arrivo la riga resta "download_avviato…" per sempre, senza errore né "Riprova".
  - **Correzione proposta:**
    - impostare lo stato "in avvio" **prima** della chiamata;
    - dopo la risposta aggiornarlo solo se nel frattempo non è arrivato un evento (`prev[model]?.status === "in avvio"`).

- [x] **Bug #22 (media, Workspace Harness): l'avvio si interrompe alla prima riga che dsh scrive su stderr**
  - **Verifica QA ciclo 6:** Verificato nel codice: `$ErrorActionPreference = 'Continue'` prima di `node`, gli `ErrorRecord` convertiti in testo, e il codice d'uscita controllato. Lo script PowerShell non è eseguibile qui su Linux.
  - **File:** `harness/avvia.ps1` (`d04bcf3`).
  - **Causa:**
    - lo script imposta `$ErrorActionPreference = 'Stop'` e legge l'output con `& node ... 2>&1 | ForEach-Object`;
    - in Windows PowerShell 5.1 ogni riga stderr di un programma nativo diventa un `NativeCommandError`, che con `Stop` termina lo script.
  - **Effetti:**
    - basta un avviso (`dsh: warning: N entries did not activate`, avvisi di Node, errori di un plugin) perché la finestra si chiuda;
    - i messaggi di avvio tradotti non compaiono;
    - il processo `node` può restare attivo senza finestra.
  - **Come riprodurlo** (stesso schema dello script):
    ```powershell
    $ErrorActionPreference = 'Stop'
    & node -e "console.log('a'); console.error('dsh: warning: 2 entries did not activate')" 2>&1 | ForEach-Object { "ricevuto: $_" }
    'fine'   # non viene mai raggiunta: NativeCommandError, exit 1
    ```
  - **Correzione proposta:**
    - impostare `$ErrorActionPreference = 'Continue'` prima di lanciare `node`;
    - nel `ForEach-Object`, convertire gli `ErrorRecord` in testo (`if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message }`);
    - in alternativa, usare `System.Diagnostics.Process` con lettura asincrona di stdout e stderr, e terminare `node` alla chiusura della finestra.

- [x] **Bug #23 (media, Workspace Harness): a ogni avvio spariscono i plugin installati dall'utente**
  - **Verifica QA ciclo 6:** Verificato: `tools/prepara-profilo.mjs` unisce invece di sovrascrivere; `npm test` della Harness passa, compreso il controllo "plugin utente conservati". Il nuovo codice di gestione dei collegamenti ha però un rischio: vedi Bug #26.
  - **File:** `harness/avvia.ps1` (`Copy-Item ... package.json -Force`).
  - **Causa:**
    - il `package.json` del profilo è il file in cui il gestore dei plugin di dsh scrive le dipendenze e l'elenco `dsh.profile.bundles`;
    - lo script lo sovrascrive a ogni avvio con il modello di `harness/profile`.
  - **Effetti:** un plugin aggiunto dalla pagina "Plugin" (o con `dsh plugin add`) funziona fino al riavvio, poi sparisce da dipendenze e bundle anche se i file restano in `node_modules`.
  - **Come riprodurlo:**
    - aggiungi `"@x/plugin"` a `dependencies` e a `dsh.profile.bundles` in `%LOCALAPPDATA%\WorkspaceOS\harness\profiles\workspace\package.json`;
    - rilancia il collegamento "Workspace Harness": il file torna al modello con 3 bundle.
  - **Correzione proposta:**
    - copiare il modello solo se il file manca;
    - altrimenti unire: aggiungere i bundle obbligatori (`dsh-base`, `dsh-web-app`, `@workspace-sm/dsh-workspace`) se assenti e conservare dipendenze e bundle dell'utente.

- [x] **Bug #24 (media, Workspace Harness): "Aggiungi plugin" fallisce sempre perché pnpm non è installato**
  - **Verifica QA ciclo 6:** Verificato: `pnpm` 10.34.7 è fissato in `harness/package.json` e nel lockfile, l'installatore ne controlla la versione e `avvia.ps1` lo mette in PATH.
  - **File:** `installer/installa.ps1` (passo 5/6) e `harness/README.md`.
  - **Causa:** il gestore dei plugin di dsh esegue `pnpm` (`dsh-plugin-manager`: `execa(options.command ?? "pnpm", …)`). L'installatore installa Node.js e il runtime con `npm`, ma non `pnpm`, che su questo PC infatti non c'è.
  - **Effetti:** pagina "Plugin" → "Aggiungi plugin" → errore `installFailurePnpmMissing` ("pnpm non trovato: non si può installare nulla"). Anche il marketplace "Scopri" non può installare nulla.
  - **Come riprodurlo:** Workspace Harness → Plugin → Aggiungi plugin → `dsh-plugin-whale-pet` → Installa.
  - **Correzione proposta:**
    - nel passo 5/6 abilitare pnpm con `corepack enable pnpm`, incluso in Node.js 22/24 (oppure `npm install -g pnpm@<versione fissata>`);
    - verificare con `pnpm --version`;
    - in alternativa, impostare `pnpmCommand` nel livello `dsh-workspace` verso un pnpm locale in `harness/node_modules/.bin`.

- [x] **Bug #25 (bassa, Workspace Harness): con LM Studio il contesto dei modelli è sovrastimato e il modello predefinito è scelto a caso**
  - **Verifica QA ciclo 6:** Verificato nel codice: per i modelli non caricati si dichiarano 4.096 token, si preferisce un modello caricato con tool calling, e se serve si carica con 16.384 token. Restano due dubbi: vedi Bug #27 e Miglioramento #18.
  - **File:** `harness/avvia.ps1` (blocco LM Studio).
  - **Causa:**
    - per i modelli non caricati lo script dichiara a dsh `max_context_length` (es. `google/gemma-4-e4b`: 131.072, `qwen3.5-4b`: 262.144);
    - ma LM Studio li carica su richiesta con la lunghezza di contesto predefinita (su questo PC `qwen3.5-4b` caricato: 8.192);
    - l'avviso "contesto troppo piccolo" esiste solo per Ollama;
    - il modello predefinito è il primo dell'elenco (qui `llama-2-7b-chat`, contesto 4.096 e senza tool calling).
  - **Effetti:** l'agente invia un prompt di circa 8.500 token a un modello caricato con 4.096 o 8.192 token di contesto, quindi la richiesta viene rifiutata o troncata. dsh non compatta perché crede di avere 131.072 token.
  - **Come riprodurlo:**
    - `GET http://127.0.0.1:1234/api/v0/models`: per i modelli `not-loaded` c'è solo `max_context_length`;
    - avvia Workspace Harness senza Ollama e invia un messaggio.
  - **Correzione proposta:**
    - usare `loaded_context_length` quando il modello è caricato;
    - altrimenti caricarlo esplicitamente con il contesto richiesto (`POST /api/v1/models/load` con `context_length: 16384`) oppure dichiarare 4.096 e avvisare;
    - scegliere come predefinito un modello con `trained_for_tool_use` (`/api/v1/models`);
    - estendere l'avviso sui 12.000 token anche a LM Studio.

---

### Miglioramenti

- [x] **Miglioramento #14: completare la configurazione di `ruff`**
  - **Verifica QA ciclo 6:** Ancora aperto: `ruff check vault_engine tests` dà ancora 5 segnalazioni (F401 in `tests/test_agent.py`, `tests/test_regressions_qa_ciclo2.py` e `ollama_hub.py`; F821 `Any` in `providers.py`). `pyproject.toml` non ha `target-version`.
  - **Verifica QA ciclo 7:** Verificato con lo strumento: `ruff 0.15.20` (`/root/.local/bin/ruff`), `ruff check vault_engine tests` → `All checks passed!`, codice d'uscita 0. `target-version = "py312"` è presente in `engine/pyproject.toml`.
  - Oltre al Miglioramento #13 (ancora aperto), `ruff` segnala:
    - `F821 Undefined name 'BaseExceptionGroup'` in `agent/mcp.py:243`: è un falso positivo, perché `pyproject.toml` non dichiara `requires-python`/`target-version` (il motore usa Python 3.12);
    - due import inutilizzati nei test: `ModelRef` in `tests/test_agent.py` e `json` in `tests/test_regressions_qa_ciclo2.py`.
  - **Proposta:** `[tool.ruff] target-version = "py312"` in `engine/pyproject.toml`, `ruff check --fix` sui test e `ruff check` tra i controlli prima del push.

- [x] **Miglioramento #15: test delle chiamate HTTP del hub Ollama a livello di trasporto**
  - **Verifica QA ciclo 6:** Aperto solo in parte: `delete` e la route `/ollama/delete` sono ora testati a livello di trasporto. `load`, `unload` (incluso il ripiego su `/api/embed`) e `pull` no.
  - **Verifica QA ciclo 7:** Verificato: `ollama_hub.set_transport()` è usato da `status`, `pull`, `installed_names`, `load`, `unload` e `delete`, e le regressioni del ciclo 5 passano.
  - **Problema:** i test di `load`, `unload`, `delete` e delle route `/ollama/*` sostituiscono le funzioni di `ollama_hub`. Così il Bug #19 è passato inosservato per tre cicli.
  - **Proposta:**
    - permettere di iniettare il `transport` (o un `AsyncClient`) in `ollama_hub`;
    - testare con `httpx.MockTransport` metodo, percorso, body e gestione degli errori di `delete`, `unload` e `load`, incluso il ripiego su `/api/embed`.

- [x] **Miglioramento #16 (sicurezza, bassa): `fetch_url` è esposto al DNS rebinding tra controllo e connessione**
  - **Verifica QA ciclo 6:** Ancora aperto: `agent/web.py` non è cambiato.
  - **Verifica QA ciclo 7:** Verificato nel codice: la connessione viene fissata sull'IP già validato (`_pinned_target`, header `Host` e SNI originali) e il corpo usa un `bytearray`. Però dietro un proxy `fetch_url` non funziona più (vedi Bug #29), e viene provato solo il primo IP validato (vedi Miglioramento #20).
  - **File:** `engine/vault_engine/agent/web.py` (`_validate_url` e `fetch_url`).
  - **Problema:**
    - `_validate_url` risolve il nome e controlla gli IP, ma poi `httpx` risolve di nuovo;
    - un DNS ostile con TTL 0 può rispondere con un IP pubblico al controllo e con `127.0.0.1` alla connessione;
    - la docstring lo riconosce. Il rischio è ridotto dall'approvazione obbligatoria, ma l'utente approva un URL che sembra pubblico.
  - **Proposta:**
    - connettersi all'IP già validato (trasporto personalizzato che fissa l'indirizzo, con `Host` e SNI originali);
    - in più, usare `bytearray` per il corpo della risposta: oggi `body += chunk` copia il buffer a ogni blocco.

- [x] **Miglioramento #17 (Workspace Harness): testi residui in inglese**
  - **Verifica QA ciclo 6:** Ancora aperto: nessuna modifica ai testi residui in inglese.
  - **Verifica QA ciclo 7:** Accettato: lo schema di `session-title-llm` in dsh 0.2.1-rc.2 non ha un campo per il prompt, e il limite è documentato in `harness/README.md`.
  - **Problema:**
    - i titoli delle sessioni generati dal modello sono in inglese (es. "Hello, I'm a language model"), perché il prompt del generatore di titoli è in inglese;
    - le descrizioni dei plugin integrati restano in inglese: dsh le legge da `locale/*.json` dei pacchetti, non dai dizionari.
  - **Proposta:**
    - nel livello `dsh-workspace`, sovrascrivere la configurazione della riga `session-title-llm` con un'istruzione in italiano, se lo schema lo consente (verificare con `dsh --dump-config-schema`);
    - documentare il limite delle descrizioni dei plugin.

---

## Verifica delle voci del ciclo 4

Corrette con `1022a7c` (fase Developer, ciclo 6) e verificate al ciclo 7: le 5 sonde di difetto del ciclo 4 ora falliscono, e il controllo positivo passa ancora.

### Bug

- [x] **Bug #16 (media, sicurezza): il filtro su `-EncodedCommand` si aggira passando gli argomenti con `Start-Process -ArgumentList`**
  - **Verifica QA ciclo 5:** ancora presente: `test_encoded_filter_bypass_cycle4` passa su tutti e 3 i casi.
  - **Verifica QA ciclo 6:** ancora presente: `tools.py` non è cambiato e `test_encoded_filter_bypass_cycle4` passa su tutti e 3 i casi.
  - **Verifica QA ciclo 7:** Verificato: le 3 forme del ciclo 4 sono bloccate (le sonde ora falliscono). Il nuovo filtro, però, guarda solo il primo token di ogni comando, e si aggira in altri 7 modi: vedi Bug #28.
  - **File:** `engine/vault_engine/agent/tools.py` (`_uses_encoded_command`).
  - **Causa:** per ogni argomento tra virgolette il filtro controlla solo la **prima parola**, e una lista separata da virgole diventa un unico token `\S+` che inizia con `,` o `@(`.
  - **Comandi codificati che passano il filtro** (sonda `test_encoded_filter_bypass_cycle4`):
    - `Start-Process powershell -ArgumentList '-NoProfile -e <b64>'`: la prima parola è `-NoProfile`;
    - `Start-Process powershell -ArgumentList '-NoProfile','-e','<b64>'`: il token è `,'-e','<b64>'`;
    - `Start-Process powershell -ArgumentList @('-e','<b64>')`.
  - **Correzione proposta:** dividere ogni argomento su spazi **e** virgole, togliere virgolette, `@(` e `)`, e controllare **ogni** parola, non solo la prima.

- [x] **Bug #17 (bassa): il filtro blocca comandi legittimi quando `powershell` o `pwsh` compaiono come argomento**
  - **Verifica QA ciclo 5:** ancora presente: `test_encoded_filter_false_positive_cycle4` passa su entrambi i casi.
  - **Verifica QA ciclo 6:** ancora presente: `test_encoded_filter_false_positive_cycle4` passa su entrambi i casi.
  - **Verifica QA ciclo 7:** Verificato: `Get-Process pwsh -ea SilentlyContinue` e `Stop-Process -Name powershell -ea 0` non sono più bloccati (le sonde ora falliscono).
  - **File:** `engine/vault_engine/agent/tools.py` (`_uses_encoded_command`).
  - **Causa:** appena trova un token con nome `powershell`/`pwsh`, il filtro esamina **tutti** i token successivi, anche quando quel nome è un argomento di un altro cmdlet. In quel caso `-ea` è l'alias comunissimo di `-ErrorAction`.
  - **Come riprodurlo:** `Get-Process pwsh -ea SilentlyContinue` e `Stop-Process -Name powershell -ea 0` vengono rifiutati come "comandi codificati". Sonda: `test_encoded_filter_false_positive_cycle4`.
  - **Correzione proposta:**
    - considerare `powershell`/`pwsh` solo in **posizione di comando**: primo token di un segmento dopo `;`, `|`, `&&`, `||` o `&`, oppure `-FilePath`/primo argomento posizionale di `Start-Process`;
    - fermare la scansione degli argomenti al separatore di comando successivo.

- [x] **Bug #18 (media): se il primo "Apri documento" fallisce, l'apertura resta bloccata fino al riavvio dell'app**
  - **Verifica QA ciclo 5:** ancora presente: `desktop/electron/main.cjs:199` usa ancora `supportedExtsPromise ??= engineFetch("/health")...` senza azzerare la cache in caso di errore.
  - **Verifica QA ciclo 6:** ancora presente: `main.cjs` non è cambiato dopo il ciclo 4.
  - **Verifica QA ciclo 7:** Verificato: la logica è spostata in `desktop/electron/openable.cjs` e la cache viene svuotata quando la promessa è rifiutata; `node --test electron/openable.test.cjs` → 6/6.
  - **File:** `desktop/electron/main.cjs` (`supportedExtensions`).
  - **Causa:** `supportedExtsPromise ??= engineFetch("/health")...` memorizza anche una promessa **rifiutata**. Se la prima richiesta capita mentre il motore non è pronto o si sta riavviando, ogni apertura successiva fallisce subito senza riprovare.
  - **Effetti:** il messaggio "apertura consentita solo per i documenti supportati dei Vault" compare per qualunque documento finché non si chiude e riapre l'app.
  - **Come riprodurlo** (simulazione Node dello stesso schema): con un `engineFetch` che fallisce solo la prima volta, i tentativi 1, 2 e 3 falliscono tutti e `/health` viene chiamato una sola volta.
  - **Correzione proposta:** `engineFetch(...).then(...).catch((e) => { supportedExtsPromise = null; throw e; })`; in aggiunta, azzerare la cache quando il motore si riavvia.

### Miglioramenti

- [x] **Miglioramento #13: segnalazioni di `ruff` e nessun test per la logica di apertura dei file**
  - **Verifica QA ciclo 5:** ancora aperto: `ruff` segnala ancora `F821 Any` in `providers.py` (righe 198 e 220) e `F401 Any` in `ollama_hub.py`. Altre segnalazioni nel Miglioramento #14.
  - **Verifica QA ciclo 6:** ancora aperto: stesse segnalazioni F821/F401 di `ruff`, e nessun test per `assertOpenableTarget`.
  - **Verifica QA ciclo 7:** Verificato: `ruff` dà 0 segnalazioni (vedi Miglioramento #14) e la logica di apertura è testata con `node --test` (6 test).
  - **`providers.py`:** `F821 Undefined name 'Any'` alle righe 198 e 220, introdotto con `ensure_loaded(events: Any = None)`. Oggi funziona solo grazie a `from __future__ import annotations`; `typing.get_type_hints(ensure_loaded)` solleverebbe `NameError`.
  - **`ollama_hub.py`:** `F401 'typing.Any' imported but unused`.
  - **Proposta:** importare `Any` in `providers.py`, togliere l'import inutile e aggiungere `ruff check` ai controlli che si lanciano prima di ogni push.
  - **Test mancanti:** la logica di `assertOpenableTarget` (Miglioramento #8 e Bug #18) non ha test automatici. Spostarla in un modulo CommonJS senza dipendenze da Electron e testarla con `node --test`.

---

## Sonde QA del ciclo 5

Le 2 sonde del ciclo 5 (Bug #19) ora falliscono, quindi il difetto è corretto. Il loro codice è stato tolto: lo sostituiscono le regressioni in `engine/tests/test_regressions_qa_ciclo5.py`.

---

## Verifica delle voci del ciclo 3

Tutte le voci del ciclo 3 sono corrette e verificate. Le regressioni sono in `engine/tests/test_regressions_qa_ciclo3.py`. Il codice delle sonde del ciclo 3 è stato tolto: ora che i difetti sono corretti lo sostituiscono quei test.

### Bug

- [x] **Bug #8 (alta): il pulsante "Scarica" della pagina Modelli fallisce sempre**
  - **Verifica QA ciclo 4:** Verificato: `on_progress` ora asincrono (`_report_pull_progress`). La sonda ora fallisce e c'è un test end-to-end che non sostituisce `start_pull`.
  - **File:** `engine/vault_engine/app.py` (`ollama_pull`) e `engine/vault_engine/ollama_hub.py` (`pull`).
  - **Causa:** `ollama_pull` passa a `start_pull` una `lambda` sincrona come `on_progress`: restituisce il risultato di `state.events.publish(...)`, cioè `None`. Ma `pull()` esegue `await on_progress(event)`, quindi alla prima riga di avanzamento solleva `TypeError: object NoneType can't be used in 'await' expression`.
  - **Effetti:** ogni download avviato dalla pagina Modelli finisce subito in "Errore". Il test di regressione `test_regressions_qa_ciclo2.py` sostituisce `start_pull` con un finto, quindi non se ne accorge.
  - **Come riprodurlo:** `POST /ollama/pull {"model":"bge-m3"}` con Ollama attivo: arriva l'evento `{"status":"errore","error":"object NoneType can't be used in 'await' expression"}`. Sonda: `test_ollama_pull_route_fails_on_first_progress_event`.
  - **Correzione proposta:** trasformare `on_progress` in una `async def`, come `_report_pull_done`, e aggiungere un test end-to-end di `/ollama/pull` che non sostituisca `start_pull`.

- [x] **Bug #9 (media): il download avviato da una ricerca o domanda (risposta 409) non segnala mai l'esito**
  - **Verifica QA ciclo 4:** Verificato: arrivano `download_completato`/`errore` anche dal percorso 409, e senza callback l'errore finisce nel log.
  - **File:** `engine/vault_engine/providers.py` (`ensure_loaded`, ramo `allow_download=False`) e `engine/vault_engine/ollama_hub.py` (`start_pull`).
  - **Causa:** `start_pull` viene chiamata senza `on_finished` né `on_error`.
  - **Effetti:**
    - Non arrivano mai `download_completato` né `errore`: la riga nella pagina Modelli resta su "success · 100%" o sull'ultima percentuale, senza ✓ e senza Riprova.
    - Se il download fallisce, l'eccezione viene scartata da `start_pull` senza nemmeno una riga nel log.
  - **Come riprodurlo:** Vault con embedding Ollama non installato; chiama `POST /vaults/{id}/search`: risponde 409, ma non arriva nessun evento finale. Sonda: `test_background_pull_from_search_reports_no_outcome`.
  - **Correzione proposta:** passare `on_finished`/`on_error` che pubblichino `download_completato`/`errore` (lo stesso `report`) e, in `start_pull`, scrivere nel log l'eccezione quando `on_error` manca.

- [x] **Bug #10 (media): la libreria segna come "installato" un modello di cui è presente solo un'altra variante**
  - **Verifica QA ciclo 4:** Verificato nel codice: confronto esatto con `:latest` più l'indicazione "altre varianti installate". `tsc` e la build passano.
  - **File:** `desktop/src/pages/Models.tsx` (`installedNames`).
  - **Causa:** dopo il Miglioramento #5 il confronto avviene senza tag da entrambe le parti: con solo `qwen2.5:0.5b` installato, la riga `qwen2.5` della libreria mostra ✓ e "installato". È l'equivalente nell'interfaccia del Bug #3, appena corretto nel motore.
  - **Effetti:** dalla libreria non si può più scaricare la versione predefinita (`:latest`) di un modello di cui si ha un'altra variante.
  - **Come riprodurlo:** installa `qwen2.5:0.5b`, apri Modelli e cerca `qwen2.5`: compare ✓ e non c'è il pulsante "Scarica".
  - **Correzione proposta:** normalizzare come nel motore: il nome della libreria diventa `nome:latest` e va confrontato esattamente con i nomi installati. Eventualmente mostrare "altre varianti installate: …".

- [x] **Bug #11 (media, sicurezza): il filtro su `-EncodedCommand` si aggira ancora**
  - **Verifica QA ciclo 4:** Verificato: i 4 aggiramenti del ciclo 3 sono bloccati. Restano altre forme con `Start-Process -ArgumentList`: vedi Bug #16.
  - **File:** `engine/vault_engine/agent/tools.py` (`_uses_encoded_command`).
  - **Comandi codificati che passano il filtro** (sonda `test_encoded_filter_bypass_cycle3`):
    - percorso completo: `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -e <b64>`, perché il token non è uguale a `powershell.exe`;
    - `& "C:\Program Files\PowerShell\7\pwsh.exe" -enc <b64>`;
    - comando annidato tra virgolette: `cmd /c "powershell -e <b64>"`, perché l'intero argomento tra virgolette è un solo token;
    - `Start-Process powershell -ArgumentList '-e <b64>'`, perché il token `-e <b64>` contiene uno spazio, quindi diventa `name = "e <b64>"` e non corrisponde.
  - **Correzione proposta:**
    - confrontare il **nome del file** del token (`PureWindowsPath(tok).name.lower()`, dopo aver tolto virgolette e `&`);
    - riesaminare in modo ricorsivo il contenuto dei token tra virgolette;
    - dividere sugli spazi gli argomenti tra virgolette prima di controllarne il prefisso.

- [x] **Bug #12 (media, sicurezza): la protezione SSRF di `fetch_url` si aggira con indirizzi IPv6 che rappresentano indirizzi IPv4**
  - **Verifica QA ciclo 4:** Verificato: `::ffff:127.0.0.1` è bloccato. Vengono usati anche `ipv4_mapped`, NAT64, `198.18.0.0/15` e le proprietà `is_private`/`is_loopback`/….
  - **File:** `engine/vault_engine/agent/web.py` (`_BLOCKED_NETWORKS` e `_validate_url`).
  - **Causa:** `::ffff:127.0.0.1` è un `IPv6Address`, che non risulta contenuto in nessuna rete IPv4 dell'elenco, quindi non viene bloccato. Lo stesso vale per `::ffff:192.168.x.x` e `::ffff:10.x.x.x`. Mancano anche `64:ff9b::/96` (NAT64) e `198.18.0.0/15`.
  - **Effetti:** su sistemi dual-stack (Windows lo è) l'agente può raggiungere servizi locali, per esempio `http://[::ffff:127.0.0.1]:11434/api/delete` di Ollama, o host della rete locale.
  - **Come riprodurlo:** `await web._validate_url("http://[::ffff:127.0.0.1]:11434/")` non solleva nulla. Sonda: `test_ssrf_ipv4_mapped_loopback_not_blocked`.
  - **Correzione proposta:**
    - se `ip.ipv4_mapped` è valorizzato, valutare l'indirizzo IPv4 contenuto;
    - in più usare le proprietà `ip.is_private`, `is_loopback`, `is_link_local`, `is_reserved`, `is_unspecified` e `is_multicast` invece del solo elenco manuale.

- [x] **Bug #13 (media, regressione): `list_directory` con il pattern predefinito `*` percorre tutto il sottoalbero e segnala `truncated: true` a torto**
  - **Verifica QA ciclo 4:** Verificato: con `*` non si scende nelle sottocartelle e `truncated` è corretto.
  - **File:** `engine/vault_engine/agent/tools.py` (`_scan_directory`).
  - **Causa:** `os.walk` scende sempre in profondità, anche quando il pattern (es. `*` o `*.pdf`) può corrispondere solo al primo livello.
  - **Effetti:**
    - con una sottocartella di oltre 20.000 file, l'elenco della sola cartella principale percorre 20.000 voci (su un NAS anche minuti);
    - risponde `truncated: true` anche se l'elenco richiesto è completo, e il modello crede che manchino dei file.
  - **Come riprodurlo:** cartella con `a.txt` e `archivio/` contenente 21.000 file; `_scan_directory(path, "*")` restituisce le 2 voci corrette ma `truncated: True`. Sonda: `test_scan_star_walks_subtree_and_reports_truncated`.
  - **Correzione proposta:**
    - calcolare dal pattern la profondità massima (numero di segmenti; illimitata solo se c'è `**`);
    - svuotare `dirnames[:]` oltre quella profondità;
    - contare nel budget solo le voci entro la profondità utile.

- [x] **Bug #14 (bassa, regressione su Windows): `list_directory` distingue tra maiuscole e minuscole**
  - **Verifica QA ciclo 4:** Verificato nel codice: `re.IGNORECASE` su Windows. Su Linux la sonda passa ancora, come previsto: lì il file system distingue maiuscole e minuscole.
  - **File:** `engine/vault_engine/agent/tools.py` (`_glob_match`).
  - **Causa:** l'espressione regolare costruita è sensibile a maiuscole e minuscole. Su Windows `Path.glob`, usato fino al ciclo 2, non lo era: `*.pdf` trovava anche `Contratto.PDF`.
  - **Come riprodurlo:** file `Contratto.PDF`; `_scan_directory(path, "*.pdf")` non restituisce nulla. Sonda: `test_scan_is_case_sensitive`.
  - **Correzione proposta:** usare `re.fullmatch(..., flags=re.IGNORECASE)` quando `os.name == "nt"`.

- [x] **Bug #15 (bassa): con `--host ::1` il motore rifiuta tutte le richieste**
  - **Verifica QA ciclo 4:** Verificato: `Host: [::1]:8765` → 200 e `Host: attacker.example` → 400 (sonda positiva `test_ipv6_loopback_host_now_accepted`).
  - **File:** `engine/vault_engine/app.py` (`TrustedHostMiddleware`) e `engine/vault_engine/__main__.py` (`LOCALHOST`).
  - **Causa:**
    - `__main__` considera `::1` un indirizzo locale e non avvisa.
    - Ma `TrustedHostMiddleware` ricava l'host con `split(":")[0]`, quindi da `[::1]:porta` ottiene `[` e risponde 400.
  - **Come riprodurlo:** `GET /health` con `Host: [::1]:8765` risponde 400. Sonda: `test_trusted_host_rejects_ipv6_loopback`.
  - **Correzione proposta:** un middleware Host personalizzato che gestisca le parentesi quadre IPv6 (`[::1]`), oppure togliere `::1` da `LOCALHOST` e documentare che è supportato solo IPv4.

---

### Miglioramenti

- [x] **Miglioramento #7 (alta, prestazioni): ogni sincronizzazione rilegge e ricalcola lo SHA-256 di tutto l'archivio**
  - **Verifica QA ciclo 4:** Verificato: una sync senza modifiche non calcola nessun SHA-256. La verifica completa è riservata a `rebuild`.
  - **File:** `engine/vault_engine/pipeline.py` (`_sync`, introdotto da `eafcb1a`).
  - **Problema:**
    - Anche i file con dimensione e data di modifica invariate vengono riletti per intero e ne viene ricalcolato lo SHA-256.
    - Il motore avvia una sync di ogni Vault sorvegliato a ogni apertura dell'app: un archivio da 100 GB su NAS viene riletto tutto a ogni avvio.
    - Viene anche riscritta una riga del manifest per ogni file (`upsert_file`), anche se non è cambiato nulla.
    - La sonda `test_unchanged_sync_rehashes_every_file` conta 40 calcoli SHA-256 su 40 file in una sync senza modifiche.
  - **Proposta:**
    - tornare a dimensione + data di modifica come controllo normale, e fare la verifica completa solo su richiesta ("Verifica integrità") o con `rebuild`;
    - in alternativa, verificare un campione a rotazione;
    - in ogni caso non riscrivere il manifest quando dimensione e data di modifica coincidono già.

- [x] **Miglioramento #8 (sicurezza): `shell:open-path` limita la cartella ma non il tipo di file**
  - **Verifica QA ciclo 4:** Verificato nel codice (`SUPPORTED_EXTS` da `/health`, `realpathSync`). Le estensioni ammesse sono solo documenti, senza formati con macro. Ha però un difetto nella cache: vedi Bug #18.
  - **File:** `desktop/electron/main.cjs` (`assertOpenableTarget`).
  - **Problema:**
    - Dentro le cartelle sorgenti di un Vault (es. una cartella "Download" o una condivisione di rete) un `.exe`, `.bat`, `.cmd`, `.js`, `.lnk` o `.url` viene comunque aperto, e quindi eseguito, da `shell.openPath`.
    - Inoltre `path.resolve` non segue i collegamenti simbolici e le giunzioni, quindi un collegamento dentro la sorgente può puntare fuori.
  - **Proposta:**
    - ammettere solo le estensioni dei documenti supportati (`SUPPORTED_EXTS`, esposte dal motore);
    - usare `fs.realpathSync` sia sul file sia sulle radici prima del confronto;
    - per i tipi non ammessi lasciare solo "mostra nella cartella".

- [x] **Miglioramento #9: le chiavi della deduplica dei download non sono normalizzate**
  - **Verifica QA ciclo 4:** Verificato: chiavi normalizzate e lock rilasciati quando non servono più.
  - **File:** `engine/vault_engine/ollama_hub.py` (`pull_dedup`, `start_pull`).
  - **Problema:**
    - `llama3` e `llama3:latest` usano chiavi diverse in `_pull_locks` e `_background_pulls`, quindi lo stesso modello può essere scaricato due volte in parallelo.
    - `_pull_locks` cresce senza limite.
  - **Proposta:** usare `normalize_name(model)` come chiave e rimuovere il lock quando non ci sono più chiamanti in attesa.

- [x] **Miglioramento #10 (prestazioni): troppe chiamate a Ollama per ogni ricerca**
  - **Verifica QA ciclo 4:** Verificato: una sola chiamata `/api/tags` per ogni `ensure_loaded`.
  - **File:** `engine/vault_engine/providers.py` (`ensure_loaded`).
  - **Problema:** per ogni modello Ollama vengono chiamati `status()` (controllo online) e `is_installed()`, che richiama `status()`: sono 4 richieste HTTP (`/api/tags` e `/api/ps` due volte) prima del preload, a ogni ricerca o domanda.
  - **Proposta:** una sola chiamata a `status()` per ogni `ensure_loaded`, riutilizzata per il controllo online e per l'elenco dei modelli installati (servirebbe solo `/api/tags`).

- [x] **Miglioramento #11: testi e configurazione**
  - **Verifica QA ciclo 4:** Verificato: testo della pagina Modelli corretto; `testserver` tolto dagli host consentiti.
  - **Testo della pagina Modelli:** dice che la ricerca in libreria è l'"unica chiamata di rete del programma", ma l'agente ha anche `web_search` (DuckDuckGo) e `fetch_url`. Correggere, per esempio in "la ricerca viene inviata a ollama.com".
  - **`testserver` tra gli host consentiti in produzione:** è il valore predefinito di TestClient. Meglio configurare i test con `TestClient(app, base_url="http://127.0.0.1")` e togliere `testserver` dall'elenco.

- [x] **Miglioramento #12: la limitazione degli eventi di avanzamento nasconde i cambi di fase**
  - **Verifica QA ciclo 4:** Verificato: l'evento parte subito anche quando cambia `status`.
  - **File:** `engine/vault_engine/ollama_hub.py` (`pull`, `throttled`).
  - **Problema:** la limitazione è solo a tempo, quindi fasi come `verifying sha256 digest` o `writing manifest` possono non comparire mai nell'interfaccia.
  - **Proposta:** inviare subito l'evento anche quando cambia `status`, non solo per lo stato finale.

---

## Verifica delle voci del ciclo 2

Tutte le voci risultano corrette e verificate. Le sonde corrispondenti sono state trasformate in test di regressione (`engine/tests/test_regressions_qa_ciclo2.py`). Nel ciclo 2 il codice delle sonde era riportato qui: ora che i difetti sono corretti lo sostituiscono quei test, quindi l'ho tolto.

### Bug

- [x] **Bug #1 (alta): con Ollama spento, ricerca e domande rispondono con un errore 500 generico invece che con un messaggio chiaro**
  - **Verifica QA ciclo 3:** Verificato: la sonda del ciclo 2 ora fallisce; con Ollama spento la ricerca risponde 502 (`ProviderError`), non più 500.
  - **File:** `engine/vault_engine/providers.py` (`ensure_loaded`) e `engine/vault_engine/app.py` (`retrieve`).
  - **Causa:**
    - Con `auto_pull=True`, se Ollama non risponde, `is_installed()` restituisce `False`.
    - Allora parte `ollama_hub.pull()`, che solleva `HubError`.
    - `HubError` non rientra nell'`except (httpx.HTTPError, KeyError, ValueError)`, quindi si propaga.
    - In questo modo cade il comportamento "best effort" promesso dalla docstring.
    - In `retrieve()` la chiamata a `ensure_loaded` non ha un `try` attorno.
  - **Effetti:**
    - `/vaults/{id}/search` e `/ask` rispondono **500 Internal Server Error**, mentre prima davano il 502 con il messaggio di `ProviderError`.
    - Anche i job di indicizzazione falliscono con il testo del pull, invece che con l'errore di embedding.
  - **Come riprodurlo:**
    1. Ollama spento, Vault con embedding `ollama/bge-m3`.
    2. `POST /vaults/{id}/search {"query":"x"}`: risponde 500.
    3. Sonde: `test_ensure_loaded_raises_when_ollama_offline` e il controllo HTTP (500).
  - **Correzione proposta:**
    - In `ensure_loaded`, catturare `ollama_hub.HubError`: registrare il problema nel log e pubblicare l'evento `errore`.
    - Oppure, in `retrieve`, convertirlo in `HTTPException(502)`.
    - Inoltre, se `status()` dice `online: False`, non tentare il pull.

- [x] **Bug #2 (media): se il download automatico fallisce, la pagina Modelli resta bloccata su "download…"**
  - **Verifica QA ciclo 3:** Verificato per i job di indicizzazione (`pull_dedup` + evento `errore`, pulsante Riprova). Restano aperti altri due percorsi di download: vedi Bug #8 (`/ollama/pull`) e Bug #9 (download avviato da ricerca/domanda).
  - **File:** `engine/vault_engine/providers.py` (`ensure_loaded`, funzione `report`) e `desktop/src/pages/Models.tsx` (`progressOf`).
  - **Causa:**
    - `ensure_loaded` pubblica `download_avviato` e poi l'avanzamento, ma quando il pull fallisce non pubblica mai `status: "errore"`.
    - `progressOf()` mostra l'avanzamento finché non arriva `download_completato`.
  - **Effetti:**
    - La riga del modello mostra la barra all'infinito.
    - Il pulsante "Scarica" non ricompare.
    - Lo stesso succede quando l'errore arriva da `/ollama/pull`: compare il messaggio, ma senza pulsante per riprovare finché non si cambia pagina.
  - **Come riprodurlo:**
    1. Vault con un modello Ollama inesistente (es. `nonexistent-model`).
    2. Avvia una sincronizzazione.
    3. Apri la pagina Modelli.
    4. Sonda: `test_ensure_loaded_pull_error_emits_no_error_event`. L'unico evento ricevuto è `["download_avviato"]`.
  - **Correzione proposta:**
    - Fare `try/except HubError` attorno al pull con `report(model, status="errore", error=str(exc))`.
    - In `Models.tsx`, se `p.error` è valorizzato, mostrare l'errore **e** il pulsante "Riprova".

- [x] **Bug #3 (media): un modello risulta "installato" anche quando ne è presente solo un'altra variante (tag diverso)**
  - **Verifica QA ciclo 3:** Verificato nel motore (`normalize_name`, confronto esatto). L'interfaccia ha ora il difetto opposto: vedi Bug #10.
  - **File:** `engine/vault_engine/ollama_hub.py` (`is_installed`).
  - **Causa:**
    - Il controllo `m.name.startswith(f"{model}:")` considera presente `llama3` quando sul disco c'è solo `llama3:8b`.
    - Ma per Ollama `llama3` significa `llama3:latest`, che non è installato.
  - **Effetti:**
    - Il download automatico viene saltato.
    - Il preload e poi la chat o l'embedding falliscono con "model not found".
  - **Come riprodurlo:** installa solo `llama3:8b` e configura l'LLM come `llama3`. Sonda: `test_is_installed_false_positive_on_other_tag`.
  - **Correzione proposta:**
    - Normalizzare il nome: se il nome non ha tag, aggiungere `:latest`.
    - Poi confrontare i nomi in modo esatto.
    - Applicare la stessa normalizzazione in `reconcile_loaded`.

- [x] **Bug #4 (media): impossibile eliminare i modelli con "/" nel nome (es. `hf.co/…`, `utente/modello`)**
  - **Verifica QA ciclo 3:** Verificato: `POST /ollama/delete` con body; la vecchia route DELETE risponde 404.
  - **File:** `engine/vault_engine/app.py` (route `DELETE /ollama/models/{name}`) e `desktop/src/api.ts` (`ollamaDelete`).
  - **Causa:**
    - Il frontend codifica il nome con `encodeURIComponent`, quindi `/` diventa `%2F`.
    - Starlette lo decodifica di nuovo in `/` prima di confrontarlo con le route.
    - `{name}` non accetta `/`, quindi la richiesta finisce in 404.
  - **Effetti:** il pulsante "Elimina" non funziona per i modelli presi da Hugging Face (`hf.co/bartowski/...`) o con un namespace.
  - **Come riprodurlo:** `DELETE /ollama/models/hf.co%2Fbartowski%2FQwen:Q4_K_M` risponde 404. Sonda: `test_delete_route_rejects_namespaced_models`.
  - **Correzione proposta:**
    - Usare `{name:path}`.
    - Oppure, meglio, `POST /ollama/delete` con body `{model}`, come già fanno `load` e `unload`.

- [x] **Bug #5 (media, sicurezza): il filtro su `-EncodedCommand` si aggira facilmente e blocca comandi legittimi**
  - **Verifica QA ciclo 3:** Verificato: i 4 aggiramenti e i 3 falsi positivi del ciclo 2 sono risolti. Restano altri aggiramenti: vedi Bug #11.
  - **File:** `engine/vault_engine/agent/tools.py` (`_uses_encoded_command`).
  - **Comandi codificati che passano il filtro:** verificati con la sonda `test_encoded_filter_bypass`.
    - `powershell /enc <b64>` e `powershell /e <b64>`: `powershell.exe` accetta anche `/` come prefisso dei parametri.
    - `powershell –e <b64>`: con il trattino lungo (en-dash, U+2013), che PowerShell tratta come `-`.
    - `powershell '-e' <b64>`: le parti tra virgolette vengono scartate dal filtro, ma PowerShell passa `-e` all'eseguibile così com'è.
  - **Comandi legittimi bloccati per errore:** verificati con la sonda `test_encoded_filter_false_positive`.
    - `node -e "console.log(1)"`
    - `Get-Content f.txt -Enc UTF8`: abbreviazione valida di `-Encoding`.
    - `Select-String … -E 'x'`
  - **Correzione proposta:**
    - Applicare il controllo solo agli argomenti che seguono `powershell`, `powershell.exe`, `pwsh` o `pwsh.exe`.
    - Accettare come prefisso `-`, `/` e i trattini Unicode (`\u2013`, `\u2014`, `\u2015`).
    - Non scartare le parti tra virgolette in posizione di argomento.
    - Bloccare anche `-EncodedArguments` / `-ea`, solo per powershell.
    - Aggiungere i casi sopra a `test_regressions_qa.py`.

- [x] **Bug #6 (bassa/media, sicurezza): l'API non controlla l'header `Host` (DNS rebinding) quando gira senza token**
  - **Verifica QA ciclo 3:** Verificato: `Host: attacker.example` → 400. Effetto collaterale su IPv6: vedi Bug #15.
  - **File:** `engine/vault_engine/app.py`.
  - **Causa:**
    - Senza `WSOS_TOKEN` (avvio manuale del motore), `require_token` non fa alcun controllo.
    - Il CORS da solo non protegge da un attacco di DNS rebinding: un sito malevolo che riassegna il proprio dominio a `127.0.0.1` diventa *same-origin*.
  - **Effetti:**
    - Le nuove route aumentano i danni possibili: `DELETE /ollama/models/{name}` cancella modelli dal disco e `/ollama/pull` scarica GB.
    - Restano esposte anche le route dell'agente.
  - **Come riprodurlo:** `GET /health` con `Host: attacker.example` risponde **200**.
  - **Correzione proposta:** aggiungere `TrustedHostMiddleware(allowed_hosts=["127.0.0.1", "localhost"])` o un controllo equivalente.

- [x] **Bug #7 (bassa): "Carica" non applica il tempo di residenza ai modelli solo-embedding**
  - **Verifica QA ciclo 3:** Verificato: il nuovo tentativo su `/api/embed` invia `keep_alive` (asserzione sul body nel test).
  - **File:** `engine/vault_engine/ollama_hub.py` (`load`, introdotto da `3df854b`).
  - **Causa:** quando `/api/generate` risponde 400 "does not support generate", il nuovo tentativo su `/api/embed` invia solo `{"model", "input"}`, senza `keep_alive`.
  - **Effetti:** un modello come `bge-m3` caricato dalla pagina Modelli usa il valore predefinito di Ollama (5 minuti) invece di `ollama_keep_alive_minutes`, quindi esce dalla memoria prima del previsto.
  - **Come riprodurlo:**
    1. Imposta il tempo di residenza a 60 minuti.
    2. Carica `bge-m3` dalla pagina Modelli.
    3. In `/api/ps`, `expires_at` risulta a circa 5 minuti.
  - **Correzione proposta:** passare `"keep_alive": f"{keep_alive_minutes}m"` anche nel nuovo tentativo su `/api/embed` e aggiungere un'asserzione sul body in `test_ollama_hub.py`.

---

### Miglioramenti

- [x] **Miglioramento #1: non bloccare le richieste HTTP mentre un modello si scarica**
  - **Verifica QA ciclo 3:** Verificato: ricerca e domanda rispondono subito 409. Il download in background però non segnala l'esito: vedi Bug #9.
  - **File:** `app.py` (`retrieve`), `agent/runner.py` e `providers.py`.
  - **Problema:** con `ollama_auto_pull=True`, una semplice ricerca o domanda resta in attesa per tutto il download (diversi GB, anche decine di minuti), mentre il client va in timeout.
  - **Proposta:**
    - Nelle richieste interattive, non scaricare.
    - Rispondere subito 409/503 con "modello in download (vedi pagina Modelli)" e avviare il download in background con la stessa logica di deduplica di `_pulls`.

- [x] **Miglioramento #2: evitare download doppi dello stesso modello**
  - **Verifica QA ciclo 3:** Verificato (`pull_dedup`, `start_pull`, `cancel_pulls`). Le chiavi non sono normalizzate: vedi Miglioramento #9.
  - **File:** `providers.py` e `app.py`.
  - **Problema:** `_pulls` deduplica solo `/ollama/pull`. Più job di Vault diversi, l'agente o una ricerca possono avviare contemporaneamente il pull dello stesso modello.
  - **Proposta:** spostare il registro `_pulls` in `ollama_hub`, con un lock per modello, e usarlo anche da `ensure_loaded`.

- [x] **Miglioramento #3: limitare gli eventi di avanzamento del download**
  - **Verifica QA ciclo 3:** Verificato: 10.000 righe producono meno di 200 eventi. Dettaglio residuo: Miglioramento #12.
  - **File:** `ollama_hub.py` (`pull`) e `app.py`.
  - **Problema:** viene inviato un evento SSE per **ogni** riga NDJSON di Ollama: per un modello da 20 GB sono migliaia al secondo verso il renderer, e React riaggiorna la pagina ogni volta. La sonda `test_pull_progress_event_flood` conta 10.000 eventi su 10.000 righe.
  - **Proposta:** al massimo 1 evento ogni 250–500 ms, oppure ogni +1%, più sempre i cambi di stato.

- [x] **Miglioramento #4: `list_directory` legge il disco sul thread principale del motore e il limite di 301 risultati non basta**
  - **Verifica QA ciclo 3:** Verificato: la scansione gira in un thread con un budget di 20.000 voci. Ha introdotto due regressioni: vedi Bug #13 e Bug #14.
  - **File:** `agent/tools.py` (`_list_directory`).
  - **Problema:**
    - `islice(..., 301)` aiuta solo quando i risultati sono tanti.
    - Con un pattern che trova poco o nulla (es. `**/*.xyz` su `C:\`), il motore percorre comunque tutto il disco.
    - La lettura avviene in modo bloccante dentro una funzione `async`, quindi ferma tutto il motore, compresi SSE e `/health`, per tutta la durata.
    - Misura: 9.000 file in 26 ms sul disco locale. Su un NAS o su `C:\` intero il tempo può arrivare a minuti.
  - **Proposta:**
    - Eseguire con `asyncio.to_thread`.
    - Impostare un limite di tempo o di file visitati (es. 20.000).
    - Restituire `truncated: true` quando il limite viene raggiunto.

- [x] **Miglioramento #5: corrispondenza dei nomi nella libreria modelli**
  - **Verifica QA ciclo 3:** Verificato: colonna `description` rimossa. Il confronto senza tag è troppo largo: vedi Bug #10.
  - **File:** `desktop/src/pages/Models.tsx`.
  - **Problema:**
    - I nomi della libreria non hanno tag (`llama3.2`), quelli installati sì (`llama3.2:latest`).
    - `installedNames.has(m.name)` e `has(m.name.split(":")[0])` sono sempre falsi, quindi un modello installato mostra ancora "Scarica".
    - `description` non viene mai valorizzata dallo scraper, quindi la colonna resta vuota.
  - **Proposta:**
    - Calcolare l'insieme dei nomi installati senza tag.
    - Rimuovere `description` o estrarla dalla scheda del modello.

- [x] **Miglioramento #6: pulizia del codice e documentazione**
  - **Verifica QA ciclo 3:** Verificato: funzioni inutilizzate rimosse, docstring corretta, download annullati alla chiusura. `ollama_auto_pull=True` è accettato come scelta di prodotto. Il nuovo testo della pagina Modelli è inesatto: vedi Miglioramento #11.
  - **Codice inutilizzato:** `ollama_hub.reconcile_loaded` e `ollama_hub.ensure_pulled` non hanno chiamanti in produzione. Inoltre `reconcile_loaded` riceve un parametro `keep_alive_minutes` che non usa. Integrarle (es. liberare RAM/VRAM dopo un job) oppure rimuoverle.
  - **Docstring di `ollama_hub`:** dice "nothing leaves the machine", ma `library_search` interroga `ollama.com` inviando la ricerca dell'utente. Correggere la docstring e segnalarlo nella pagina Modelli.
  - **`ollama_auto_pull` attivo per impostazione predefinita:** un nome di modello sbagliato nelle impostazioni avvia download di diversi GB senza conferma. Valutare il default `False` o una conferma nella UI.
  - **`_cors_origin_regex()`:** viene calcolata all'import del modulo. Va documentato che `WSOS_TOKEN` deve essere già impostato prima dell'import, cosa che oggi Electron garantisce.
  - **Download in corso alla chiusura del motore:** i task in `_pulls` non vengono annullati nello shutdown del `lifespan`. Annullarli insieme ai worker.

---

## Sonde QA del ciclo 8 (riproducibili)

Per eseguirle: salva il codice qui sotto in `engine/tests/_probe_qa8.py` (file temporaneo, da non committare) e lancia `uv run pytest -q tests/_probe_qa8.py` dalla cartella `engine`. `test_encoded_filter_bypass_cycle8` passa quando il difetto è presente: al ciclo 8 passa su tutti e 4 i casi. `test_cycle7_cases_blocked` e `test_no_false_positive` sono controlli positivi e devono passare sempre.

| Sonda | Voce |
|---|---|
| `test_encoded_filter_bypass_cycle8` (4 casi) | Bug #31 |
| `test_cycle7_cases_blocked` (5 casi) | controllo positivo (Bug #28 e #16) |
| `test_no_false_positive` (3 casi) | controllo positivo (Bug #17) |

Le 8 sonde del ciclo 7 ora falliscono, quindi quei difetti sono corretti. Il loro codice è stato tolto: lo sostituiscono le regressioni in `engine/tests/test_regressions_qa_ciclo5.py`.

<details><summary>Codice delle sonde del ciclo 8</summary>

```python
"""Sonde QA ciclo 8: ciascun test PASSA se il difetto ipotizzato è presente."""
import pytest

from vault_engine.agent.tools import _uses_encoded_command


@pytest.mark.parametrize("cmd", [
    "power`shell -e SGVsbG8=",            # backtick: PowerShell lo ignora davanti a una lettera normale
    "powershell -e`nc SGVsbG8=",          # backtick dentro lo switch
    ". powershell -e SGVsbG8=",           # operatore punto (dot-source) come &
    "& $env:ComSpec /c powershell -e SGVsbG8=",  # cmd.exe tramite variabile d'ambiente
])
def test_encoded_filter_bypass_cycle8(cmd):
    assert not _uses_encoded_command(cmd)


@pytest.mark.parametrize("cmd", [
    "(powershell -e SGVsbG8=)",
    "if ($true) { powershell -e SGVsbG8= }",
    '&"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -enc SGVsbG8=',
    "saps powershell -ArgumentList '-e SGVsbG8='",
    "Start-Process powershell -ArgumentList @('-e','SGVsbG8=')",
])
def test_cycle7_cases_blocked(cmd):
    """Controllo positivo: deve PASSARE a difetti corretti."""
    assert _uses_encoded_command(cmd)


@pytest.mark.parametrize("cmd", [
    "Get-Process pwsh -ea SilentlyContinue",
    "if (Test-Path x) { Get-Process powershell -ea 0 }",
    'node -e "console.log(1)"',
])
def test_no_false_positive(cmd):
    """Controllo positivo: comandi legittimi non bloccati."""
    assert not _uses_encoded_command(cmd)
```

</details>

---

## Soluzioni applicate (fase Developer, ciclo 2)

Tutte le sonde del ciclo 2 sono state trasformate in regressioni con asserzione invertita in `engine/tests/test_regressions_qa_ciclo2.py` (più aggiornamenti a `test_ollama_hub.py` e `test_regressions_qa.py`).

- **Bug #1 — `ensure_loaded` con Ollama spento.** `providers.ensure_loaded` ora interroga prima `ollama_hub.status()`: con `online: False` salta pull e preload (niente `HubError` non catturato) e lascia fallire la chiamata embed/chat con il consueto `ProviderError` → HTTP 502 pulito da `retrieve()`. Test: `test_ensure_loaded_tolerates_ollama_offline`, `test_ensure_loaded_offline_does_not_attempt_pull`.
- **Bug #2 — pagina Modelli bloccata su "download…".** Il fallimento del pull pubblica ora `status: "errore"` con il messaggio (backend) e `Models.tsx` mostra l'errore con pulsante **Riprova** che ripulisce lo stato e riavvia il download (sia nella lista "Installati" che in "Libreria"). Test: `test_ensure_loaded_pull_failure_emits_error_event`.
- **Bug #3 — `is_installed` con tag diverso.** Aggiunto `normalize_name()` (nome senza tag → `:latest`, anche con prefisso `hf.co/…`); confronto esatto sui nomi normalizzati. Test: `test_is_installed_requires_exact_tag_after_normalization`, `test_normalize_name_appends_latest_only_to_tagless_tail`.
- **Bug #4 — modelli con "/" nel nome.** La cancellazione è ora `POST /ollama/delete` con body `{model}` (come `load`/`unload`): la vecchia route DELETE è rimossa. `api.ts` aggiornato. Verificato live contro Ollama. Test: `test_delete_route_accepts_namespaced_models`, `test_old_delete_route_is_gone`.
- **Bug #5 — filtro EncodedCommand.** `_uses_encoded_command` riscritto: il controllo si applica solo ai token che seguono un'invocazione esplicita `powershell`/`powershell.exe`/`pwsh`/`pwsh.exe`; prefissi accettati `-`, `/`, `–` (U+2013), `—` (U+2014), `―` (U+2015); i token quotati contano comunque (PowerShell li re-interpreta come switch); blocca ogni prefisso di `-EncodedCommand`/`-EncodedArguments` **e** gli alias `-ec`/`-ea` (attenzione: "encoded…" inizia con "en", quindi gli alias non sono prefissi). Falsi positivi eliminati: `node -e`, `Get-Content -Enc UTF8`, `Select-String -E`. Test aggiornati in `test_regressions_qa.py` (14 casi bloccanti, 9 consentiti).
- **Bug #6 — header Host senza token.** `TrustedHostMiddleware(allowed_hosts=["127.0.0.1", "localhost", "*.localhost", "testserver"])` attivo solo quando `WSOS_TOKEN` è assente (valutato a import; testserver è l'host di default di TestClient). Verificato live: `Host: attacker.example` → 400. Test: `test_trusted_host_middleware_installed_only_without_token`, `test_health_rejects_foreign_host_header`.
- **Bug #7 — keep_alive mancante nel fallback embed.** `ollama_hub.load()` passa ora `keep_alive` (stesso body di `/api/generate`) anche nel tentativo su `/api/embed`. Test: asserzione sul body in `test_load_falls_back_to_embed_for_embedding_only_models`.
- **Miglioramento #1 — richieste bloccate dal download.** `ensure_loaded` ha il parametro `allow_download`: con `False` (usato da `retrieve()` per search/ask) il modello mancante avvia il download in background (con dedup ed eventi) e la richiesta risponde subito **409** con "modello in download". I job di indicizzazione e l'agente mantengono il download bloccante. Test: `test_ensure_loaded_notify_mode_raises_and_pulls_in_background`.
- **Miglioramento #2 — download doppi.** Registro condiviso in `ollama_hub`: `pull_dedup()` (lock per modello + riverifica post-attesa) usato da `ensure_loaded`, e `start_pull()` per i download background usato da `/ollama/pull` e dalla modalità 409; `cancel_pulls()` nello shutdown del lifespan. Test: `test_pull_dedup_skips_second_caller`.
- **Miglioramento #3 — flood di eventi.** `ollama_hub.pull()` throttle a 1 evento ogni 300 ms; stato terminale (`success`/errore) sempre consegnato. Test: `test_pull_throttles_progress_events` (10.000 righe → <200 eventi, ultimo = success).
- **Miglioramento #4 — `list_directory` bloccante e senza cap di visita.** `_list_directory` esegue la scansione in `asyncio.to_thread` (motore e SSE non si bloccano) con budget di 20.000 entry visitate (`truncated: true` quando raggiunto) e matching glob corretto sui separatori (`*`/`?` non attraversano `/`, `**/` = zero o più directory). Test: `test_scan_directory_visit_budget`, `test_scan_directory_matches_dirs_and_nested_files` + regressioni ciclo 1.
- **Miglioramento #5 — nomi libreria vs installati.** `Models.tsx` confronta i nomi senza tag (`m.name.split(":")[0]`), quindi `llama3.2` risulta "installato"; colonna `description` rimossa (mai popolata dallo scraper; la label resta visibile).
- **Miglioramento #6 — pulizia.** `ensure_pulled` e `reconcile_loaded` rimosse (senza chiamanti in produzione); docstring di `ollama_hub` corretta (la ricerca libreria invia la query a ollama.com) con nota visibile nella pagina Modelli; download attivi annullati nello shutdown; `_cors_origin_regex` documentata come valutata a import; `ollama_auto_pull` resta `True` per scelta di prodotto (gestione automatica dei modelli richiesta), con mitigazioni: eventi di errore visibili, dedup, 409 nelle richieste interattive.

**Note per il Tester**: le sonde `_probe_qa.py` che passavano "col difetto" ora falliscono per costruzione (asserzioni invertite nelle regressioni). Il test `test_ensure_loaded_raises_when_ollama_offline` della sonda era atteso come `HubError`: il comportamento corretto è **non** sollevare (best effort), quindi la regressione corrispondente asserisce il completamento senza eccezioni. La sonda `test_delete_route_rejects_namespaced_models` resta valida (la vecchia route DELETE risponde 404 anche dopo la fix, per design).

---

## Soluzioni applicate (fase Developer, ciclo 3)

Tutte le sonde del ciclo 3 sono state trasformate in regressioni con asserzione invertita in `engine/tests/test_regressions_qa_ciclo3.py` (più aggiornamenti a `test_regressions_qa_ciclo2.py` e `test_coverage_misc.py`). Suite completa su Windows: **146 passati, 0 falliti** (`pytest -m "not live"`); frontend: `tsc --noEmit` e `vite build` vanno a buon fine.

- **Bug #8 — download dalla pagina Modelli sempre in errore.** In `app.py` la route `/ollama/pull` passava una lambda sincrona come `on_progress` (restituiva `None`, che `pull()` poi attendeva). Ora il callback è la nuova `async def _report_pull_progress(model, p)`, come già `_report_pull_done`/`_report_pull_error`. Test end-to-end **senza stub** di `start_pull`: `test_ollama_pull_route_reports_progress_and_completes` (transport HTTP finto, evento finale = `download_completato`).
- **Bug #9 — download da ricerca/domanda (409) senza esito.** In `providers.ensure_loaded` il ramo `allow_download=False` passa ora `on_finished`/`on_error` che pubblicano `download_completato`/`errore` con lo stesso `report`; in `ollama_hub.start_pull`, se manca `on_error`, l'eccezione viene comunque scritta nel log (`log.error`). Test: `test_background_pull_from_search_reports_error`, `test_background_pull_from_search_reports_completion`, `test_start_pull_logs_error_when_no_callback`.
- **Bug #10 — libreria segna "installato" con solo un'altra variante.** `Models.tsx`: nuova `normalizeName` identica a `ollama_hub.normalize_name` (nome senza tag → `:latest`, attento al prefisso `hf.co/…`); il confronto è esatto sui nomi normalizzati. Se esistono solo altre varianti (es. `qwen2.5:0.5b` per la riga `qwen2.5`) la riga mostra "altre varianti installate: …" e il pulsante "Scarica" resta disponibile.
- **Bug #11 — filtro `-EncodedCommand` aggirabile.** `_uses_encoded_command` riscritto di nuovo: (1) l'eseguibile è riconosciuto per **nome file** (`PureWindowsPath(tok).name`) dopo aver tolto virgolette e `&` — quindi anche `C:\…\powershell.exe` e `& "C:\Program Files\…\pwsh.exe"`; (2) il contenuto dei token tra virgolette che contiene spazi è riesaminato ricorsivamente come comando (`cmd /c "powershell -e …"`); (3) gli argomenti tra virgolette con spazi (`'-e <b64>'` da `Start-Process -ArgumentList`) sono valutati sulla prima parola. Nessun nuovo falso positivo sui 9 comandi legittimi del ciclo 2, verificati + 2 aggiunti (`Test-Path "…\pwsh.exe"`, `Get-Item …\powershell.exe | …`). Test: `test_encoded_filter_bypass_cycle3_blocked` (4 casi), `test_encoded_filter_cycle3_no_new_false_positives`.
- **Bug #12 — SSRF con IPv4-mapped IPv6.** `agent/web.py`: nuova `_is_blocked(ip)` — se `ip.ipv4_mapped` è valorizzato si valuta l'IPv4 contenuto; in più si usano `is_private`/`is_loopback`/`is_link_local`/`is_reserved`/`is_unspecified`/`is_multicast` oltre all'elenco manuale, che ora include `64:ff9b::/96` (NAT64) e `198.18.0.0/15`. Test: `test_ssrf_ipv4_mapped_ipv6_blocked`, `test_ssrf_nat64_and_benchmark_ranges_blocked`, `test_ssrf_public_literal_still_allowed`. **Nota per il Tester:** `is_private` copre anche le documentation range (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24): per questo i due test `fetch_url` che usavano `203.0.113.10` come "IP pubblico" ora usano `93.184.216.34` (aggiornati in `test_coverage_misc.py`).
- **Bug #13 — `list_directory` con `*` percorreva tutto il sottoalbero.** `_scan_directory`: nuova `_pattern_max_depth` (n. di segmenti; illimitata solo con `**`); `os.walk` pota `dirnames[:]` oltre la profondità utile e il budget di 20.000 voci conta solo le voci raggiungibili dal pattern. Con `*` una sottocartella da 21.000 file non viene più traversata e `truncated` resta `False`. Test: `test_scan_star_does_not_walk_subtree`, `test_scan_prunes_only_beyond_pattern_depth`.
- **Bug #14 — `list_directory` case-sensitive su Windows.** `_glob_match` usa `re.IGNORECASE` quando `os.name == "nt"` (come il `Path.glob` usato fino al ciclo 2). Test: `test_scan_matches_case_insensitively_on_windows` (platform-aware).
- **Bug #15 — `--host ::1` rifiutava tutto.** `TrustedHostMiddleware` (che spezzava `[::1]:porta` su `:`) sostituito da un middleware ASGI dedicato `LocalhostOnlyMiddleware` in `app.py`: interpreta le parentesi quadre IPv6 e ammette `127.0.0.1`, `::1`, `localhost`, `*.localhost`. Test: `test_localhost_only_middleware_accepts_ipv6_loopback` (`[::1]:8765` → 200, `attacker.example` → 400).
- **Miglioramento #7 — sync che rilegge tutto l'archivio.** `pipeline._sync`: tornato a dimensione+mtime come controllo normale, **senza** ricalcolo SHA-256 né riscrittura del manifest per i file invariati; la verifica completa dei contenuti resta disponibile con `rebuild` (force=True), che riesegue hash+parsing di tutto. Un file solo "toccato" (mtime cambiata) finisce in `todo` e viene hash-verificato singolarmente da `prepare_file` come prima. Test: `test_unchanged_sync_does_not_rehash` (0 hash su 40 file alla seconda sync); il test del ciclo precedente `test_sync_rehashes_files_with_preserved_timestamps` è diventato `test_rebuild_catches_files_with_preserved_timestamps`: la sync normale ignora il file manomesso (totale 0), la rebuild lo rileva (totale 2).
- **Miglioramento #8 — `shell:open-path` senza controllo del tipo.** `desktop/electron/main.cjs`: `assertOpenableTarget(target, {forOpen})` — confronto su `fs.realpathSync` di file **e** radici (niente fuga via symlink/giunzioni); per l'apertura (`shell:open-path`) sono ammesse solo le estensioni `SUPPORTED_EXTS` lette da `/health` del motore (cache a primo uso). I tipi non ammessi (`.exe`, `.bat`, `.lnk`, …) restano raggiungibili solo da "Mostra nella cartella", che non esegue nulla.
- **Miglioramento #9 — chiavi deduplica non normalizzate.** `pull_dedup` e `start_pull` usano `normalize_name(model)` come chiave di `_pull_locks`/`_background_pulls` (`llama3` ≡ `llama3:latest`); i lock sono rimossi con un contatore di chiamanti quando nessuno li usa più. Test: `test_pull_dedup_normalizes_keys_and_releases_lock`, `test_start_pull_joins_normalized_duplicate`.
- **Miglioramento #10 — troppe chiamate a Ollama per ricerca.** `ensure_loaded` fa ora UNA sola `GET /api/tags` per chiamata (nuova `ollama_hub.installed_names`), riusata per il controllo online e per l'elenco installati: da 4 richieste HTTP per modello a 1 per chiamata. Test: `test_ensure_loaded_uses_single_tags_call` (una `/api/tags`, nessuna `/api/ps`, nessun pull se già installato).
- **Miglioramento #11 — testi e configurazione.** Pagina Modelli: il testo ora dice che "la ricerca viene inviata a ollama.com" e che anche l'agente può accedere alla rete (ricerca web, apertura pagine) solo dopo approvazione. `testserver` rimosso dagli host consentiti: il middleware ammette solo loopback e i test usano `TestClient(app, base_url="http://127.0.0.1")` (fixture di `test_regressions_qa_ciclo2.py` aggiornata).
- **Miglioramento #12 — throttle che nascondeva i cambi di fase.** `ollama_hub.pull`: l'evento è inviato subito anche quando cambia `status` (es. `verifying sha256 digest`, `writing manifest`), non solo a tempo o allo stato finale. Test: `test_pull_emits_phase_changes_despite_throttle` (fasi visibili, flood comunque assente: <50 eventi su ~400 righe).

**Note per il Tester**: la sonda del Bug #15 usava il `TestClient` di default (host `testserver`): con il Miglioramento #11 quell'host è respinto per design — le regressioni usano `base_url="http://127.0.0.1"` e impostano l'header `Host` esplicito dove serve. La sonda del Miglioramento #7 asseriva il vecchio comportamento (40 hash): la regressione corrispondente asserisce 0 hash in sync e copre la verifica completa via `rebuild` (vedi sopra). Il percorso UI del Bug #10 è verificato da `tsc --noEmit` + build; non esistono test unitari del frontend.

---

## Soluzioni applicate (fase Developer, ciclo 5)

Suite su Windows 11: motore **152 passati, 0 falliti** (compresi i test `live`; 5 nuovi in `engine/tests/test_regressions_qa_ciclo5.py`); interfaccia: `tsc --noEmit` e `vite build` vanno a buon fine; Workspace Harness: `npm test` passa (nuovo controllo sul `package.json` del profilo).

- **Bug #19 — "Elimina" sempre in errore 500.** `ollama_hub.delete` usa `client.request("DELETE", …/api/delete, json={"model": …})`. Test **senza sostituire** `ollama_hub.delete`, con `httpx.MockTransport`: metodo, percorso e body della richiesta (`test_hub_delete_sends_delete_with_json_body`), 404 → `HubError` (`test_hub_delete_unknown_model_raises_huberror`), Ollama spento → `HubError` (`test_hub_delete_offline_raises_huberror`), route completa scarico + eliminazione → 200 (`test_delete_route_unloads_then_deletes`) e modello inesistente → 502 (`test_delete_route_unknown_model_answers_502`). Prova reale contro Ollama 0.40.6: un modello inesistente dà `HubError … HTTP 404 … not found` invece del `TypeError`. Copre in parte il Miglioramento #15 (solo `delete`).
- **Bug #20 — avanzamento dei download automatici invisibile.** `Models.tsx`: `normalizeName` è ora a livello di modulo; lo stato `pulls` è indicizzato con il nome normalizzato (eventi e righe usano la stessa chiave, `bge-m3` ≡ `bge-m3:latest`) e conserva il nome richiesto per "Riprova". Nuova scheda **"Download in corso"** per i download che non corrispondono a nessuna riga (modello non installato e non tra i risultati della libreria), con avanzamento, errore e "Riprova"; la cella di avanzamento è condivisa con la libreria (`progressCell`).
- **Bug #21 — errore immediato sovrascritto.** `pull()` imposta lo stato "in avvio" **prima** di `api.ollamaPull` e dopo la risposta lo sostituisce con "download_avviato" solo se è ancora lo stesso oggetto (nessun evento arrivato nel frattempo); se la richiesta fallisce toglie solo il proprio segnaposto e mostra la notifica.
- **Bug #22 — avvio interrotto dalla prima riga stderr.** `harness/avvia.ps1`: `$ErrorActionPreference = 'Continue'` prima di lanciare `node`; nel `ForEach-Object` gli `ErrorRecord` diventano testo (`$_.Exception.Message`). Se dsh termina con un codice diverso da 0 la finestra resta aperta con il messaggio. Verificato in Windows PowerShell 5.1: con la riga stderr `dsh: warning: …` lo script prosegue; avvio completo su cartelle temporanee con un avviso reale di dsh su stderr ("skipping profile bundle …") e poi "Workspace Harness è pronto".
- **Bug #23 — plugin dell'utente persi a ogni avvio.** Nuovo `harness/tools/prepara-profilo.mjs`, chiamato da `avvia.ps1` al posto di `Copy-Item -Force`: al primo avvio copia il modello; poi aggiunge in testa solo i bundle Workspace mancanti e conserva dipendenze e bundle dell'utente (tollera il BOM; un file illeggibile viene salvato come `package.json.non-valido` e ricreato). Test in `npm test`: «package.json del profilo: plugin utente conservati (Bug #23)»; verificato anche dall'avvio reale.
- **Bug #24 — pnpm assente.** `pnpm` 10.34.7 è una dipendenza fissata di `harness/package.json` (si installa con il passo 5/6, anche con `--omit=dev`); `avvia.ps1` mette `harness\node_modules\.bin` in testa al `PATH` di dsh e avvisa se pnpm manca; l'installatore mostra la versione di pnpm o un avviso. Verificato: `execa("pnpm")` (come il gestore dei plugin) e `dsh plugin --profile workspace --version` rispondono 10.34.7. Non verificato: l'installazione di un plugin reale dalla pagina "Plugin" (richiede rete e un pacchetto del marketplace).
- **Bug #25 — contesto LM Studio sovrastimato e predefinito casuale.** `avvia.ps1`: per i modelli caricati usa `loaded_context_length`, per quelli non caricati dichiara 4.096 token (il contesto con cui LM Studio li carica su richiesta), non più `max_context_length`. Il predefinito (se manca `workspace-agent` di Ollama) è nell'ordine: caricato con almeno 12.000 token e tool calling, caricato con almeno 12.000 token, con tool calling (`trained_for_tool_use` da `/api/v1/models`, se disponibile), primo dell'elenco. Se il predefinito non ha contesto sufficiente lo script lo carica con `POST /api/v1/models/load` e `context_length: 16384`, altrimenti avvisa. L'avviso «troppo pochi per l'agente» vale ora anche per LM Studio. **Non verificato dal vivo:** LM Studio non era avviabile su questo PC durante la correzione (`lms server start`: daemon non trovato); lo script si analizza senza errori in PowerShell 5.1.

**Note per il Tester:** le sonde del ciclo 5 per il Bug #19 (`test_hub_delete_raises_typeerror`, `test_delete_route_answers_500`) ora falliscono per costruzione. Restano aperte le voci del ciclo 4 (Bug #16, #17, #18, Miglioramento #13) e i Miglioramenti #14, #16, #17 del ciclo 5; il #15 è coperto solo per `delete`. Da verificare nel ciclo 6: con LM Studio attivo, la scelta del modello predefinito e il caricamento a 16.384 token (Bug #25); un plugin reale installato dalla pagina "Plugin" (Bug #24). `ruff` segnala ancora `typing.Any` inutilizzato in `ollama_hub.py`, già nel Miglioramento #14.

---

## Soluzioni applicate (fase Developer, ciclo 6)

Suite su Windows 11: motore **164 passati, 0 falliti, 1 deselezionato** (`pytest -m "not live"`; 1 nuovo file `engine/tests/test_regressions_qa_ciclo5.py` esteso con le regressioni dei Bug #16/#17 e del Miglioramento #15/#16); interfaccia: `tsc --noEmit` e `vite build` vanno a buon fine; processo Electron: `node --test electron/openable.test.cjs` 6/6; Workspace Harness: `npm test` passa tutti e 7 i controlli (aggiunto quello sul Bug #26).

- **Bug #16 — filtro `-EncodedCommand` aggirabile con `Start-Process -ArgumentList`.** `agent/tools.py` (`_uses_encoded_command`) riscritto a segmenti di comando: `_segment_tokens` divide ogni argomento su spazi **e** virgole, toglie virgolette, `@(`, `)` e `,`, e il controllo di ogni parola avviene su **tutte** le parole, non solo sulla prima. I nomi di eseguibile riconosciuti includono anche `cmd` e `start` con gestione ricorsiva di `/c`. Le 3 forme di aggiramento del ciclo 4 sono bloccate. Test: `test_encoded_filter_bypass_cycle4_blocked` (3 casi) e `test_encoded_filter_no_new_false_positives` in `engine/tests/test_regressions_qa_ciclo5.py`.
- **Bug #17 — falsi positivi su `powershell`/`pwsh` come argomento.** Lo scanner ora considera `powershell`/`pwsh` solo in **posizione di comando** (primo token di un segmento dopo `;`, `|`, `&&`, `||`, `&`, oppure `-FilePath`/primo argomento posizionale di `Start-Process`) e si ferma al separatore di comando successivo: `-ea` dopo `Get-Process pwsh` è di nuovo l'alias di `-ErrorAction`. Test: `test_encoded_filter_false_positive_cycle4_unblocked` (2 casi).
- **Bug #18 — "Apri documento" bloccato dopo il primo fallimento.** La logica di `assertOpenableTarget` è stata spostata in un nuovo modulo CommonJS senza dipendenze da Electron, `desktop/electron/openable.cjs`: la promessa della cache è azzerata in caso di errore (`.catch((e) => { cache = null; throw e })`), quindi il tentativo successivo riprova davvero. `main.cjs` usa il modulo. Test: `desktop/electron/openable.test.cjs` con `node --test` (6 test, inclusa la simulazione del primo tentativo fallito e dei 3 successivi).
- **Miglioramento #13 — `ruff` e test di `assertOpenableTarget`.** `typing.Any` importato in `providers.py` (le annotazioni di `ensure_loaded` risolvono ora con `get_type_hints`), import inutilizzati rimossi da `ollama_hub.py`, `test_agent.py` e `test_regressions_qa_ciclo2.py`; test di `assertOpenableTarget` in `openable.test.cjs` (vedi Bug #18). `ruff` non è installato nella venv di sviluppo: le 5 segnalazioni elencate dal Tester (2× F821 `Any`, F401 `Any`, 2× F401 nei test) corrispondono uno-a-uno alle modifiche sopra, verificabili a vista; chiedo conferma con `ruff check` nel ciclo 7.
- **Miglioramento #14 — configurazione di `ruff`.** `engine/pyproject.toml` ora dichiara `[tool.ruff] target-version = "py312"`: il falso positivo `F821 BaseExceptionGroup` in `agent/mcp.py:243` sparisce (Python 3.12).
- **Miglioramento #15 — test HTTP del hub a livello di trasporto (completato).** `ollama_hub` accetta ora l'iniezione del trasporto: `set_transport()` / `_transport` usati da `status`, `pull`, `installed_names`, `load`, `unload` e `delete` (i test non sostituiscono più le funzioni del modulo). Test in `test_regressions_qa_ciclo5.py`: `test_hub_load_sends_generate_with_keep_alive`, `test_hub_load_falls_back_to_embed_with_keep_alive` (ripiego `/api/embed` con `keep_alive` nel body), `test_hub_unload_sends_post`, `test_hub_pull_posts_to_api_pull`.
- **Miglioramento #16 — DNS rebinding su `fetch_url`.** `agent/web.py`: `_pinned_target` fissa l'IP già validato nella connessione (transport con `sni_hostname` e header `Host` originali), eliminando la finestra tra il controllo e la risoluzione del nome; il corpo della risposta usa `bytearray`. Test: `test_fetch_url_pins_validated_ip` e `test_fetch_url_uses_bytearray_body` in `test_regressions_qa_ciclo5.py`.
- **Miglioramento #17 — testi residui in inglese.** Verificato con `dsh --dump-config-schema` (dsh 0.2.1-rc.2): lo schema della riga `session-title-llm` espone solo `targetWords`/`targetCjkCharacters`/`maxInputBytes`/`maxOutputTokens`/`timeoutMs`/`provider`/`model` — **nessun campo prompt**, quindi la sovrascrittura proposta non è applicabile; il system prompt integrato dice già "Use the language of the messages". Limite documentato in `harness/README.md` (nuova nota "Due limiti noti del runtime dsh 0.2.1-rc.2"), insieme alla nota su pnpm/corepack del Bug #24. Le descrizioni dei plugin in inglese restano un limite del runtime, non del profilo.
- **Bug #26 — junction orfano che blocca l'avvio / cancella l'altra copia.** `harness/avvia.ps1`: il ciclo dei plugin usa `Get-Item -LiteralPath $link -Force` (non segue il collegamento) invece di `Test-Path`; la rimozione avviene solo con `[System.IO.Directory]::Delete($link)` (senza ricorsione, mai `Remove-Item -Recurse` su un junction); il confronto del target usa `[IO.Path]::GetFullPath` su entrambi i lati. Una cartella reale (non link) continua a essere sostituita normalmente. Test mirato: `harness/tools/testa-junction.ps1` (5 scenari: junction valido intoccato, orfano rilevato, orfano sostituito, riattacco verso altra copia, contenuto dell'altra copia intatto) richiamato anche da `npm test` della Harness (solo su Windows). **Verificato su Windows 11 con PowerShell 5.1: 5/5.**
- **Bug #27 — contesto Ollama sempre 4.096 e file utente riscritto.** `harness/avvia.ps1`: per i modelli già caricati si legge `context_length` da `/api/ps` (con guardia se il campo manca); poi `num_ctx` del Modelfile; poi `OLLAMA_CONTEXT_LENGTH` da ambiente utente e macchina; infine 4.096. La riscrittura silenziosa di `cordis.patch.yml` è stata tolta: ora solo un avviso suggerisce `workspace-agent` (sintassi verificata; la logica contro Ollama reale non è stata eseguita).
- **Miglioramento #18 — seconda istanza in LM Studio.** `harness/avvia.ps1`: prima di caricare il modello scelto con 16.384 token, se è già `loaded` con contesto insufficiente lo script scarica prima la vecchia istanza (`POST /api/v1/models/unload`, eventuale errore ignorato) e poi carica. **Verificabile solo su Windows con LM Studio 0.3.x attivo: non eseguito dal vivo in questa correzione** (come per il Bug #25 al ciclo 5).

**Note per il Tester:** le sonde del ciclo 4 (`test_encoded_filter_bypass_cycle4`, `test_encoded_filter_false_positive_cycle4`) ora falliscono per costruzione: le regressioni con asserzione invertita sono in `engine/tests/test_regressions_qa_ciclo5.py`. Il controllo "profilo workspace composto da dsh" di `harness/tools/test.mjs` copia ora i plugin invece di collegarli con junction: i junction verso la repo venivano seguiti dal gestore plugin di dsh (pnpm), che **svuotava** `harness/plugins/*` — stessa causa del Bug #26; con la copia la repo resta intatta a ogni `npm test`. Da verificare nel ciclo 7: su Windows, Bug #27 e Miglioramento #18 contro Ollama/LM Studio reali, e `ruff check` (segnalazioni attese: 0).


---

## Soluzioni applicate (fase Developer, ciclo 7)

Suite su Windows 11: motore **179 passati, 0 falliti, 1 deselezionato** (`pytest -m "not live"`; +15 test in `engine/tests/test_regressions_qa_ciclo5.py`); processo Electron 6/6; Workspace Harness `npm test` **8 controlli su 8** (nuovo controllo BOM); interfaccia `tsc --noEmit` e `vite build` a buon fine. Le prove Windows delle 23:00 (commento sulla PR #21, id 6302773000) hanno confermato **Bug #26 e Bug #27** e hanno mostrato che il Miglioramento #18 **non funzionava su LM Studio 0.4.25** (`unload` con il nome dà 400 `Missing required field 'instance_id'`): questa correzione lo risolve.

- **Bug #28 — filtro aggirabile con blocchi e sottoespressioni.** `agent/tools.py` (`_segment_tokens`): i separatori di segmento ora includono anche `( ) { }` e le parole chiave di blocco (`if/elseif/else/try/catch/finally/foreach/while/for/do/switch`): in PowerShell un comando può iniziare dopo di essi, non solo dopo `; | & && ||`. `&` attaccato a un percorso tra virgolette (`&"C:\…\pwsh.exe"`) viene staccato PRIMA della tokenizzazione, così la testa non si spezza; un `(` attaccato al token precedente (`@(`, `Write-Host()`) NON apre una posizione di comando (altrimenti `-ArgumentList @('-e',…)` spezzerebbe gli argomenti), mentre `$(` resta separatore. Aggiunto `saps` (alias di `Start-Process`) a `_LAUNCHER_NAMES`. Tutti i 7 casi della sonda ciclo 7 sono bloccati; i 13 comandi legittimi (cicli 2-6 + 6 nuovi con blocchi e parentesi) restano permessi. Test: `test_encoded_filter_bypass_cycle7_blocked` (7 casi) e casi aggiunti a `test_encoded_filter_no_new_false_positives`.
- **Bug #29 — `fetch_url` inutilizzabile dietro proxy.** `agent/web.py`: nuova `_proxy_for(url)` (variabili d'ambiente +, su Windows, registro di sistema; rispetta `proxy_bypass`). Con proxy attivo la richiesta va **per nome host** (il DNS lo fa il proxy; il pinning per IP era inutile e il `CONNECT` per IP numerico viene rifiutato dai proxy che filtrano per nome): la protezione SSRF resta sul controllo iniziale e su ogni hop dei redirect. Senza proxy il pinning dell'Miglioramento #16 resta invariato. I test sul pinning esistenti sono ora ermetici (`getproxies` azzerato via monkeypatch, essenziale negli ambienti con proxy di sistema). Test: `test_fetch_url_behind_proxy_uses_hostname_not_ip`.
- **Bug #30 — BOM UTF-8 perso.** `harness/avvia.ps1` e `harness/tools/testa-junction.ps1` risalvati in UTF-8 **con BOM** (come `installer/*.ps1`): in Windows PowerShell 5.1 i messaggi accentati tornano leggibili. Nuovo controllo in `harness/tools/test.mjs` che verifica il BOM di ogni `*.ps1` di `harness/` e `installer/` (8º controllo della suite, eseguito su ogni piattaforma).
- **Miglioramento #18 — unload con `instance_id` (corretto alla luce della prova su 0.4.25).** `harness/avvia.ps1`: lo scarico usa `instance_id` letto da `/api/v1/models` → `loaded_instances[].id` (su 0.4.25 il nome dà 400), con ripiego su `{"model": …}` per le versioni che lo accettano. Se NESSUN tentativo riesce, lo script **avvisa e salta il caricamento** invece di creare in silenzio una seconda istanza (`modello:2`, doppia RAM/VRAM, richieste ancora instradate sulla prima). Da riverificare su Windows con LM Studio reale: lo scenario è ora coperto dal passo 4 della procedura del Tester.
- **Miglioramento #19 — test che prova la copia invece del codice vero.** La logica di collegamento è stata estratta in `harness/tools/collegamenti.ps1` (`Installa-PluginWorkspace -Profilo … -Harness …`) e richiamata sia da `avvia.ps1` sia da `tools/testa-junction.ps1`: il test esercita il codice di produzione, non una copia. Aggiunto il caso mancante dello scenario 2: collegamento orfano verso `A-spostata` con `A` **ancora assente** quando la funzione viene chiamata verso `B` — il collegamento orfano viene sostituito senza toccare `A-spostata`. Test su Windows 11/PS 5.1: 5/5.
- **Miglioramento #20 — solo il primo IP.** `agent/web.py` (`fetch_url`): al `ConnectError` sul primo IP validato si riprova con i successivi, in ordine, fino all'esaurimento (poi l'errore si propaga come prima). Test: `test_fetch_url_tries_next_validated_ip_on_connect_error` (primo IP rifiutato, secondo OK, entrambi registrati).

**Note per il Tester:** le sonde del ciclo 7 (`test_encoded_filter_bypass_cycle7`) ora falliscono per costruzione; le regressioni con asserzione invertita sono in `test_regressions_qa_ciclo5.py`. Restano aperte solo le tre voci con prove Windows dal vivo: **Bug #26 e Bug #27 hanno output eseguiti il 20/10 alle 23:00** (commento PR 6302773000 — `C:\Prove` eliminato dopo le prove, quindi per eventuali riprese servono due nuove copie); **Miglioramento #18** va riprovato con LM Studio 0.4.x dopo questa correzione (la procedura è la stessa del ciclo 7). Il modello `qwen3:4b-instruct` resta installato in Ollama sulla macchina di prova.

---

## Soluzioni applicate (fase Developer, ciclo 8)

Suite su Windows 11: motore **189 passati, 0 falliti, 1 deselezionato** (`pytest -m "not live"`; nuovo file `engine/tests/test_regressions_qa_ciclo8.py` con 10 test); Workspace Harness `npm test` **8 controlli su 8**, compreso quello sul BOM (tutti e 5 gli `*.ps1` tracciati iniziano con `EF BB BF`, ricontrollati dopo le modifiche); interfaccia non toccata in questo ciclo. Sintassi di `avvia.ps1` verificata con il parser di PowerShell (`[System.Management.Automation.Language.Parser]::ParseFile`, 0 errori).

- **Bug #31 — aggiramenti residui del filtro `-EncodedCommand`.** `engine/vault_engine/agent/tools.py`: (1) nuova `_deobfuscate_backticks` all'ingresso di `_uses_encoded_command` (quindi anche per le righe annidate): le sequenze di escape reali `` `n `` `` `t `` `` `r `` `` `0 `` `` `a `` `` `b `` `` `f `` `` `v `` diventano il carattere di controllo — così `` powershell -e`nc … `` si spezza nei token `-e` e `nc` e `-e` viene riconosciuto — l'accento grave a fine riga unisce le righe e ogni altro accento grave viene tolto (`` power`shell `` → `powershell`); (2) l'operatore punto (dot-source) in testa a un segmento è trattato come `&`, quindi `. powershell -e …` viene scansionato; (3) `$env:ComSpec` (e la forma `${env:ComSpec}`) è riconosciuto come `cmd`, quindi `& $env:ComSpec /c powershell -e …` riesamina il resto della riga. Le 4 sonde del ciclo 8 sono bloccate; i 13 comandi legittimi dei cicli precedenti più 5 nuovi (dot-source di script, `$env:ComSpec /c dir`, `` `n `` in stringa, `` `% ``) restano permessi. Test: `engine/tests/test_regressions_qa_ciclo8.py`.
- **Miglioramento #21 — ricarico LM Studio più robusto.** `harness/avvia.ps1`: lo scarico riguarda ora **tutte** le `loaded_instances` del modello, non solo la prima (una `modello:2` residua non resta più in memoria); un solo scarico fallito basta a saltare il caricamento con avviso. Dopo il `load` si rilegge `/api/v1/models` e si avvisa se le istanze non sono esattamente una con contesto ≥ 16.384 (`config.context_length`), aggiornando il `contextWindow` registrato al valore reale invece che al valore atteso.
- **Miglioramento #22 — contesto impostato dall'app Ollama.** `harness/avvia.ps1`: se ci sono modelli nascosti e `OLLAMA_CONTEXT_LENGTH` non è impostata, una riga aggiuntiva spiega il rimedio (variabile `OLLAMA_CONTEXT_LENGTH` oppure `INSTALLA.bat` per `workspace-agent`), perché il valore delle Impostazioni dell'app non è leggibile dall'esterno. Documentato in `harness/README.md` («Contesto di Ollama»). Non implementato il caricamento leggero `POST /api/generate` + `/api/ps` (opzione «in alternativa»): occuperebbe RAM/VRAM a ogni avvio.

**Note per il Tester:** la sonda del ciclo 8 (`test_encoded_filter_bypass_cycle8`) ora fallisce per costruzione; le regressioni con asserzione invertita sono in `engine/tests/test_regressions_qa_ciclo8.py`. **Miglioramento #18** resta da riprovare dal vivo su LM Studio 0.4.x con la procedura in «Prova da eseguire su Windows»: la verifica interagisce con LM Studio (carico/scarico modelli) e va fatta a mano sulla macchina, non dall'automazione. Nella stessa sessione si possono controllare anche i casi limite del Miglioramento #21 (più istanze `lms load` dello stesso modello prima dell'avvio; atteso: tutte scaricate, una sola istanza a 16.384 dopo).
