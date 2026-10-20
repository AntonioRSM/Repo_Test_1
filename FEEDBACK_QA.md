# FEEDBACK QA – ciclo 3

**Ambito:** commit `8da243b..21b104e` sul branch `claude/workspace-os-installer` (PR #20):
- `eafcb1a`: Miglioramenti #1-#9 (prestazioni, sicurezza, copertura dei test);
- `21b104e`: correzioni di Bug #1-#7 e Miglioramenti #1-#6 del ciclo 2.

**Esito:** NON APPROVATO. Le voci del ciclo 2 sono risolte e i test passano, ma ci sono 8 bug nuovi (uno ad alta priorità) e 6 miglioramenti.

**Test eseguiti (Linux):**
- Suite completa (`uv run pytest`): 123 passati, 1 saltato, 1 fallito. Il test fallito è `test_mcp.py::test_stdio_server_lifecycle_and_secrets`, che usa DPAPI e funziona solo su Windows: è atteso.
- Interfaccia: `npm ci` e `npm run build` vanno a buon fine.
- Sonde del ciclo 2: 11 su 13 ora falliscono, quindi quei difetti sono corretti. Le altre 2 passano per come sono scritte: la vecchia route DELETE risponde 404 per scelta, e la sonda su `list_directory` misurava solo il tempo.
- Sonde del ciclo 3: 11 su 11 confermano i difetti qui sotto. Il codice è in fondo al file.
- Ho escluso un sospetto: se l'avvio del motore fallisce, il nuovo `__main__._serve` non si blocca, perché uvicorn esce con codice 3.

---

## Ciclo 3 – Bug

- [ ] **Bug #8 (alta): il pulsante "Scarica" della pagina Modelli fallisce sempre**
  - **File:** `engine/vault_engine/app.py` (`ollama_pull`) e `engine/vault_engine/ollama_hub.py` (`pull`).
  - **Causa:** `ollama_pull` passa a `start_pull` una `lambda` sincrona come `on_progress`: restituisce il risultato di `state.events.publish(...)`, cioè `None`. Ma `pull()` esegue `await on_progress(event)`, quindi alla prima riga di avanzamento solleva `TypeError: object NoneType can't be used in 'await' expression`.
  - **Effetti:** ogni download avviato dalla pagina Modelli finisce subito in "Errore". Il test di regressione `test_regressions_qa_ciclo2.py` sostituisce `start_pull` con un finto, quindi non se ne accorge.
  - **Come riprodurlo:** `POST /ollama/pull {"model":"bge-m3"}` con Ollama attivo: arriva l'evento `{"status":"errore","error":"object NoneType can't be used in 'await' expression"}`. Sonda: `test_ollama_pull_route_fails_on_first_progress_event`.
  - **Correzione proposta:** trasformare `on_progress` in una `async def`, come `_report_pull_done`, e aggiungere un test end-to-end di `/ollama/pull` che non sostituisca `start_pull`.

- [ ] **Bug #9 (media): il download avviato da una ricerca o domanda (risposta 409) non segnala mai l'esito**
  - **File:** `engine/vault_engine/providers.py` (`ensure_loaded`, ramo `allow_download=False`) e `engine/vault_engine/ollama_hub.py` (`start_pull`).
  - **Causa:** `start_pull` viene chiamata senza `on_finished` né `on_error`.
  - **Effetti:**
    - Non arrivano mai `download_completato` né `errore`: la riga nella pagina Modelli resta su "success · 100%" o sull'ultima percentuale, senza ✓ e senza Riprova.
    - Se il download fallisce, l'eccezione viene scartata da `start_pull` senza nemmeno una riga nel log.
  - **Come riprodurlo:** Vault con embedding Ollama non installato; chiama `POST /vaults/{id}/search`: risponde 409, ma non arriva nessun evento finale. Sonda: `test_background_pull_from_search_reports_no_outcome`.
  - **Correzione proposta:** passare `on_finished`/`on_error` che pubblichino `download_completato`/`errore` (lo stesso `report`) e, in `start_pull`, scrivere nel log l'eccezione quando `on_error` manca.

- [ ] **Bug #10 (media): la libreria segna come "installato" un modello di cui è presente solo un'altra variante**
  - **File:** `desktop/src/pages/Models.tsx` (`installedNames`).
  - **Causa:** dopo il Miglioramento #5 il confronto avviene senza tag da entrambe le parti: con solo `qwen2.5:0.5b` installato, la riga `qwen2.5` della libreria mostra ✓ e "installato". È l'equivalente nell'interfaccia del Bug #3, appena corretto nel motore.
  - **Effetti:** dalla libreria non si può più scaricare la versione predefinita (`:latest`) di un modello di cui si ha un'altra variante.
  - **Come riprodurlo:** installa `qwen2.5:0.5b`, apri Modelli e cerca `qwen2.5`: compare ✓ e non c'è il pulsante "Scarica".
  - **Correzione proposta:** normalizzare come nel motore: il nome della libreria diventa `nome:latest` e va confrontato esattamente con i nomi installati. Eventualmente mostrare "altre varianti installate: …".

- [ ] **Bug #11 (media, sicurezza): il filtro su `-EncodedCommand` si aggira ancora**
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

- [ ] **Bug #12 (media, sicurezza): la protezione SSRF di `fetch_url` si aggira con indirizzi IPv6 che rappresentano indirizzi IPv4**
  - **File:** `engine/vault_engine/agent/web.py` (`_BLOCKED_NETWORKS` e `_validate_url`).
  - **Causa:** `::ffff:127.0.0.1` è un `IPv6Address`, che non risulta contenuto in nessuna rete IPv4 dell'elenco, quindi non viene bloccato. Lo stesso vale per `::ffff:192.168.x.x` e `::ffff:10.x.x.x`. Mancano anche `64:ff9b::/96` (NAT64) e `198.18.0.0/15`.
  - **Effetti:** su sistemi dual-stack (Windows lo è) l'agente può raggiungere servizi locali, per esempio `http://[::ffff:127.0.0.1]:11434/api/delete` di Ollama, o host della rete locale.
  - **Come riprodurlo:** `await web._validate_url("http://[::ffff:127.0.0.1]:11434/")` non solleva nulla. Sonda: `test_ssrf_ipv4_mapped_loopback_not_blocked`.
  - **Correzione proposta:**
    - se `ip.ipv4_mapped` è valorizzato, valutare l'indirizzo IPv4 contenuto;
    - in più usare le proprietà `ip.is_private`, `is_loopback`, `is_link_local`, `is_reserved`, `is_unspecified` e `is_multicast` invece del solo elenco manuale.

- [ ] **Bug #13 (media, regressione): `list_directory` con il pattern predefinito `*` percorre tutto il sottoalbero e segnala `truncated: true` a torto**
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

- [ ] **Bug #14 (bassa, regressione su Windows): `list_directory` distingue tra maiuscole e minuscole**
  - **File:** `engine/vault_engine/agent/tools.py` (`_glob_match`).
  - **Causa:** l'espressione regolare costruita è sensibile a maiuscole e minuscole. Su Windows `Path.glob`, usato fino al ciclo 2, non lo era: `*.pdf` trovava anche `Contratto.PDF`.
  - **Come riprodurlo:** file `Contratto.PDF`; `_scan_directory(path, "*.pdf")` non restituisce nulla. Sonda: `test_scan_is_case_sensitive`.
  - **Correzione proposta:** usare `re.fullmatch(..., flags=re.IGNORECASE)` quando `os.name == "nt"`.

- [ ] **Bug #15 (bassa): con `--host ::1` il motore rifiuta tutte le richieste**
  - **File:** `engine/vault_engine/app.py` (`TrustedHostMiddleware`) e `engine/vault_engine/__main__.py` (`LOCALHOST`).
  - **Causa:**
    - `__main__` considera `::1` un indirizzo locale e non avvisa.
    - Ma `TrustedHostMiddleware` ricava l'host con `split(":")[0]`, quindi da `[::1]:porta` ottiene `[` e risponde 400.
  - **Come riprodurlo:** `GET /health` con `Host: [::1]:8765` risponde 400. Sonda: `test_trusted_host_rejects_ipv6_loopback`.
  - **Correzione proposta:** un middleware Host personalizzato che gestisca le parentesi quadre IPv6 (`[::1]`), oppure togliere `::1` da `LOCALHOST` e documentare che è supportato solo IPv4.

---

## Ciclo 3 – Miglioramenti

- [ ] **Miglioramento #7 (alta, prestazioni): ogni sincronizzazione rilegge e ricalcola lo SHA-256 di tutto l'archivio**
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

- [ ] **Miglioramento #8 (sicurezza): `shell:open-path` limita la cartella ma non il tipo di file**
  - **File:** `desktop/electron/main.cjs` (`assertOpenableTarget`).
  - **Problema:**
    - Dentro le cartelle sorgenti di un Vault (es. una cartella "Download" o una condivisione di rete) un `.exe`, `.bat`, `.cmd`, `.js`, `.lnk` o `.url` viene comunque aperto, e quindi eseguito, da `shell.openPath`.
    - Inoltre `path.resolve` non segue i collegamenti simbolici e le giunzioni, quindi un collegamento dentro la sorgente può puntare fuori.
  - **Proposta:**
    - ammettere solo le estensioni dei documenti supportati (`SUPPORTED_EXTS`, esposte dal motore);
    - usare `fs.realpathSync` sia sul file sia sulle radici prima del confronto;
    - per i tipi non ammessi lasciare solo "mostra nella cartella".

- [ ] **Miglioramento #9: le chiavi della deduplica dei download non sono normalizzate**
  - **File:** `engine/vault_engine/ollama_hub.py` (`pull_dedup`, `start_pull`).
  - **Problema:**
    - `llama3` e `llama3:latest` usano chiavi diverse in `_pull_locks` e `_background_pulls`, quindi lo stesso modello può essere scaricato due volte in parallelo.
    - `_pull_locks` cresce senza limite.
  - **Proposta:** usare `normalize_name(model)` come chiave e rimuovere il lock quando non ci sono più chiamanti in attesa.

- [ ] **Miglioramento #10 (prestazioni): troppe chiamate a Ollama per ogni ricerca**
  - **File:** `engine/vault_engine/providers.py` (`ensure_loaded`).
  - **Problema:** per ogni modello Ollama vengono chiamati `status()` (controllo online) e `is_installed()`, che richiama `status()`: sono 4 richieste HTTP (`/api/tags` e `/api/ps` due volte) prima del preload, a ogni ricerca o domanda.
  - **Proposta:** una sola chiamata a `status()` per ogni `ensure_loaded`, riutilizzata per il controllo online e per l'elenco dei modelli installati (servirebbe solo `/api/tags`).

- [ ] **Miglioramento #11: testi e configurazione**
  - **Testo della pagina Modelli:** dice che la ricerca in libreria è l'"unica chiamata di rete del programma", ma l'agente ha anche `web_search` (DuckDuckGo) e `fetch_url`. Correggere, per esempio in "la ricerca viene inviata a ollama.com".
  - **`testserver` tra gli host consentiti in produzione:** è il valore predefinito di TestClient. Meglio configurare i test con `TestClient(app, base_url="http://127.0.0.1")` e togliere `testserver` dall'elenco.

- [ ] **Miglioramento #12: la limitazione degli eventi di avanzamento nasconde i cambi di fase**
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

## Sonde QA del ciclo 3 (riproducibili)

Per eseguirle: salva il codice qui sotto in `engine/tests/_probe_qa3.py` (file temporaneo, da non committare) e lancia `uv run pytest -q tests/_probe_qa3.py` dalla cartella `engine`. Ogni test passa quando il difetto è presente: al ciclo 3 ne passano 11 su 11. Quando un bug viene corretto, la sonda va trasformata in test di regressione con l'asserzione invertita.

| Sonda | Voce |
|---|---|
| `test_ollama_pull_route_fails_on_first_progress_event` | Bug #8 |
| `test_background_pull_from_search_reports_no_outcome` | Bug #9 |
| `test_encoded_filter_bypass_cycle3` (4 casi) | Bug #11 |
| `test_ssrf_ipv4_mapped_loopback_not_blocked` | Bug #12 |
| `test_scan_star_walks_subtree_and_reports_truncated` | Bug #13 |
| `test_scan_is_case_sensitive` | Bug #14 |
| `test_trusted_host_rejects_ipv6_loopback` | Bug #15 |
| `test_unchanged_sync_rehashes_every_file` | Miglioramento #7 |

<details><summary>Codice delle sonde del ciclo 3</summary>

```python
"""Sonde QA ciclo 3: ciascun test PASSA se il difetto ipotizzato è presente."""
import asyncio
import ipaddress

import httpx
import pytest

from vault_engine import ollama_hub, providers
from vault_engine.agent.tools import _uses_encoded_command, _scan_directory
from vault_engine.config import ModelRef


def fake_ollama(tags, pull_lines):
    def handler(req: httpx.Request):
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n, "size": 1} for n in tags]})
        if req.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        if req.url.path == "/api/pull":
            return httpx.Response(200, text="\n".join(pull_lines))
        return httpx.Response(200, json={})
    return httpx.MockTransport(handler)


def patch_transport(monkeypatch, transport):
    orig = httpx.AsyncClient.__init__
    def init(self, *a, **kw):
        kw["transport"] = transport
        orig(self, *a, **kw)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)


def test_ollama_pull_route_fails_on_first_progress_event(monkeypatch):
    """/ollama/pull passa una lambda sincrona (publish -> None) come on_progress, ma pull() la await."""
    from fastapi.testclient import TestClient
    from vault_engine import app as appmod
    monkeypatch.delenv("WSOS_TOKEN", raising=False)
    patch_transport(monkeypatch, fake_ollama([], ['{"status":"pulling manifest"}', '{"status":"success"}']))
    seen = []
    with TestClient(appmod.app) as c:
        monkeypatch.setattr(appmod.state.events, "publish", lambda e: seen.append(e))
        assert c.post("/ollama/pull", json={"model": "bge-m3"}).status_code == 202
        async def wait():
            for _ in range(100):
                if any(e.get("status") in ("errore", "download_completato") for e in seen):
                    return
                await asyncio.sleep(0.02)
        c.portal.call(wait)
    final = [e for e in seen if e.get("status") in ("errore", "download_completato")]
    assert final and final[-1]["status"] == "errore" and "await" in final[-1]["error"]


def test_background_pull_from_search_reports_no_outcome(monkeypatch):
    """Percorso 409 (allow_download=False): start_pull senza on_finished/on_error."""
    patch_transport(monkeypatch, fake_ollama([], ['{"error":"file does not exist"}']))
    seen = []
    class Ev:
        def publish(self, e): seen.append(e)
    ref = ModelRef(provider="ollama", model="modello-inesistente")
    async def run():
        with pytest.raises(providers.ProviderError):
            await providers.ensure_loaded({}, [(ref, "embedding")], events=Ev(), allow_download=False)
        await asyncio.sleep(0.3)
    asyncio.run(run())
    assert not any(e.get("status") in ("errore", "download_completato") for e in seen)


@pytest.mark.parametrize("cmd", [
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -e SGVsbG8=",
    r'& "C:\Program Files\PowerShell\7\pwsh.exe" -enc SGVsbG8=',
    'cmd /c "powershell -e SGVsbG8="',
    "Start-Process powershell -ArgumentList '-e SGVsbG8='",
])
def test_encoded_filter_bypass_cycle3(cmd):
    assert not _uses_encoded_command(cmd)


def test_ssrf_ipv4_mapped_loopback_not_blocked():
    from vault_engine.agent import web
    ip = ipaddress.ip_address("::ffff:127.0.0.1")
    assert not any(ip in net for net in web._BLOCKED_NETWORKS)
    asyncio.run(web._validate_url("http://[::ffff:127.0.0.1]:11434/api/tags"))  # nessuna WebError


def test_scan_star_walks_subtree_and_reports_truncated(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    deep = tmp_path / "archivio"
    deep.mkdir()
    for i in range(21_000):
        (deep / f"f{i}").touch()
    out = _scan_directory(tmp_path, "*")
    assert {e["name"] for e in out["entries"]} == {"a.txt", "archivio"}
    assert out["truncated"] is True  # falso: il livello richiesto è completo


def test_scan_is_case_sensitive(tmp_path):
    (tmp_path / "Contratto.PDF").write_text("x")
    assert _scan_directory(tmp_path, "*.pdf")["entries"] == []  # su Windows Path.glob lo trovava


def test_trusted_host_rejects_ipv6_loopback(monkeypatch):
    from fastapi.testclient import TestClient
    from vault_engine import app as appmod
    monkeypatch.delenv("WSOS_TOKEN", raising=False)
    with TestClient(appmod.app) as c:
        assert c.get("/health", headers={"Host": "[::1]:8765"}).status_code == 400


def test_unchanged_sync_rehashes_every_file(tmp_path, monkeypatch, fake_embeddings):
    """Una sync senza modifiche rilegge e calcola lo SHA-256 di TUTTI i file (e riscrive il manifest)."""
    from vault_engine import pipeline
    from vault_engine.config import SettingsStore
    from vault_engine.events import EventBus
    from vault_engine.vaults import VaultConfig, VaultRegistry
    monkeypatch.setenv("WSOS_DATA_DIR", str(tmp_path / "data"))
    src = tmp_path / "src"
    src.mkdir()
    for i in range(40):
        (src / f"nota{i}.txt").write_text(f"contenuto {i}")
    calls = []
    orig = pipeline.sha256_file
    monkeypatch.setattr(pipeline, "sha256_file", lambda p: calls.append(p) or orig(p))

    async def scenario():
        events = EventBus()
        events.bind(asyncio.get_running_loop())
        registry = VaultRegistry()
        jobs = pipeline.JobManager(registry, SettingsStore(), events)
        vault = registry.create(VaultConfig(name="T", sources=[str(src)], embedding=ModelRef(provider="lmstudio", model="fake")))
        async def run():
            job = jobs.submit(vault.config.id, "sync")
            while job.status in ("queued", "running"):
                await asyncio.sleep(0.05)
            return job
        await run()
        calls.clear()
        second = await run()
        await jobs.shutdown()
        return second
    second = asyncio.run(scenario())
    assert second.total == 0 and len(calls) == 40
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
