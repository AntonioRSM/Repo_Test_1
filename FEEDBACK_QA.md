# FEEDBACK QA – ciclo 5

**Ambito:**
- di nuovo l'intervallo `dbacb23..7ec57c8` sul branch `claude/workspace-os-installer` (PR #20): `5b64cbe` (correzioni QA) e `7ec57c8` (gestione dei modelli Ollama), con tutto il codice che ne dipende nello stato attuale;
- i commit arrivati sulla PR dopo il ciclo 4: `79acbc3` (README, `start.cmd`), `9d6b2be` (Ollama nell'installatore), `d04bcf3` (Workspace Harness).

**Esito:** NON APPROVATO.
- Dopo il ciclo 4 non c'è stato nessun commit di correzione, quindi le 4 voci aperte del ciclo 4 lo sono ancora.
- Il ciclo 5 trova 7 bug nuovi. Il più grave è il Bug #19: "Elimina" nella pagina Modelli non ha mai funzionato.
- Il ciclo 5 trova anche 4 miglioramenti.

**Test eseguiti (Windows 11, Smart App Control attivo, Ollama 0.40.6 e LM Studio attivi):**
- **Motore:**
  - `pytest` (suite completa, compresi i test `live` sui modelli reali): **147 passati**, 0 falliti;
  - `pytest -m "not live"`: 146 passati, 1 deselezionato;
  - su Windows passa anche il test DPAPI che su Linux falliva.
- **Interfaccia:** `npm install` e `npm run build` (`tsc --noEmit` + `vite build`) vanno a buon fine.
- **Workspace Harness:** `npm test` passa (traduzioni, plugin generati, profilo composto con `dsh --dump-config`).
- **`ruff check vault_engine tests`** (ruff 0.8.4): 6 segnalazioni (vedi Miglioramento #13 e Miglioramento #14).
- **Sonde del ciclo 4:** 6 su 6 passano ancora, quindi i Bug #16 e #17 sono ancora presenti.
- **Sonde del ciclo 5:** 2 su 2 confermano il Bug #19. I Bug #22-#25 si riproducono con i passi indicati nelle voci.
- **Prova reale:** `ollama_hub.delete` chiamato contro Ollama locale con un modello inesistente fallisce con `TypeError` prima di qualunque richiesta HTTP.

---

## Ciclo 5 – Bug

- [ ] **Bug #19 (alta): "Elimina" nella pagina Modelli fallisce sempre con un errore 500**
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

- [ ] **Bug #20 (media): l'avanzamento dei download avviati automaticamente non compare da nessuna parte**
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

- [ ] **Bug #21 (bassa): un errore immediato del download può essere sovrascritto e la riga resta su "download_avviato…" senza "Riprova"**
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

- [ ] **Bug #22 (media, Workspace Harness): l'avvio si interrompe alla prima riga che dsh scrive su stderr**
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

- [ ] **Bug #23 (media, Workspace Harness): a ogni avvio spariscono i plugin installati dall'utente**
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

- [ ] **Bug #24 (media, Workspace Harness): "Aggiungi plugin" fallisce sempre perché pnpm non è installato**
  - **File:** `installer/installa.ps1` (passo 5/6) e `harness/README.md`.
  - **Causa:** il gestore dei plugin di dsh esegue `pnpm` (`dsh-plugin-manager`: `execa(options.command ?? "pnpm", …)`). L'installatore installa Node.js e il runtime con `npm`, ma non `pnpm`, che su questo PC infatti non c'è.
  - **Effetti:** pagina "Plugin" → "Aggiungi plugin" → errore `installFailurePnpmMissing` ("pnpm non trovato: non si può installare nulla"). Anche il marketplace "Scopri" non può installare nulla.
  - **Come riprodurlo:** Workspace Harness → Plugin → Aggiungi plugin → `dsh-plugin-whale-pet` → Installa.
  - **Correzione proposta:**
    - nel passo 5/6 abilitare pnpm con `corepack enable pnpm`, incluso in Node.js 22/24 (oppure `npm install -g pnpm@<versione fissata>`);
    - verificare con `pnpm --version`;
    - in alternativa, impostare `pnpmCommand` nel livello `dsh-workspace` verso un pnpm locale in `harness/node_modules/.bin`.

- [ ] **Bug #25 (bassa, Workspace Harness): con LM Studio il contesto dei modelli è sovrastimato e il modello predefinito è scelto a caso**
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

## Ciclo 5 – Miglioramenti

- [ ] **Miglioramento #14: completare la configurazione di `ruff`**
  - Oltre al Miglioramento #13 (ancora aperto), `ruff` segnala:
    - `F821 Undefined name 'BaseExceptionGroup'` in `agent/mcp.py:243`: è un falso positivo, perché `pyproject.toml` non dichiara `requires-python`/`target-version` (il motore usa Python 3.12);
    - due import inutilizzati nei test: `ModelRef` in `tests/test_agent.py` e `json` in `tests/test_regressions_qa_ciclo2.py`.
  - **Proposta:** `[tool.ruff] target-version = "py312"` in `engine/pyproject.toml`, `ruff check --fix` sui test e `ruff check` tra i controlli prima del push.

- [ ] **Miglioramento #15: test delle chiamate HTTP del hub Ollama a livello di trasporto**
  - **Problema:** i test di `load`, `unload`, `delete` e delle route `/ollama/*` sostituiscono le funzioni di `ollama_hub`. Così il Bug #19 è passato inosservato per tre cicli.
  - **Proposta:**
    - permettere di iniettare il `transport` (o un `AsyncClient`) in `ollama_hub`;
    - testare con `httpx.MockTransport` metodo, percorso, body e gestione degli errori di `delete`, `unload` e `load`, incluso il ripiego su `/api/embed`.

- [ ] **Miglioramento #16 (sicurezza, bassa): `fetch_url` è esposto al DNS rebinding tra controllo e connessione**
  - **File:** `engine/vault_engine/agent/web.py` (`_validate_url` e `fetch_url`).
  - **Problema:**
    - `_validate_url` risolve il nome e controlla gli IP, ma poi `httpx` risolve di nuovo;
    - un DNS ostile con TTL 0 può rispondere con un IP pubblico al controllo e con `127.0.0.1` alla connessione;
    - la docstring lo riconosce. Il rischio è ridotto dall'approvazione obbligatoria, ma l'utente approva un URL che sembra pubblico.
  - **Proposta:**
    - connettersi all'IP già validato (trasporto personalizzato che fissa l'indirizzo, con `Host` e SNI originali);
    - in più, usare `bytearray` per il corpo della risposta: oggi `body += chunk` copia il buffer a ogni blocco.

- [ ] **Miglioramento #17 (Workspace Harness): testi residui in inglese**
  - **Problema:**
    - i titoli delle sessioni generati dal modello sono in inglese (es. "Hello, I'm a language model"), perché il prompt del generatore di titoli è in inglese;
    - le descrizioni dei plugin integrati restano in inglese: dsh le legge da `locale/*.json` dei pacchetti, non dai dizionari.
  - **Proposta:**
    - nel livello `dsh-workspace`, sovrascrivere la configurazione della riga `session-title-llm` con un'istruzione in italiano, se lo schema lo consente (verificare con `dsh --dump-config-schema`);
    - documentare il limite delle descrizioni dei plugin.

---

## Verifica delle voci del ciclo 4

Dopo `77f0aed` (ciclo 4) sul branch non c'è nessun commit di correzione: le voci restano aperte. Le sonde del ciclo 4 passano ancora tutte (6 su 6).

### Bug

- [ ] **Bug #16 (media, sicurezza): il filtro su `-EncodedCommand` si aggira passando gli argomenti con `Start-Process -ArgumentList`**
  - **Verifica QA ciclo 5:** ancora presente: `test_encoded_filter_bypass_cycle4` passa su tutti e 3 i casi.
  - **File:** `engine/vault_engine/agent/tools.py` (`_uses_encoded_command`).
  - **Causa:** per ogni argomento tra virgolette il filtro controlla solo la **prima parola**, e una lista separata da virgole diventa un unico token `\S+` che inizia con `,` o `@(`.
  - **Comandi codificati che passano il filtro** (sonda `test_encoded_filter_bypass_cycle4`):
    - `Start-Process powershell -ArgumentList '-NoProfile -e <b64>'`: la prima parola è `-NoProfile`;
    - `Start-Process powershell -ArgumentList '-NoProfile','-e','<b64>'`: il token è `,'-e','<b64>'`;
    - `Start-Process powershell -ArgumentList @('-e','<b64>')`.
  - **Correzione proposta:** dividere ogni argomento su spazi **e** virgole, togliere virgolette, `@(` e `)`, e controllare **ogni** parola, non solo la prima.

- [ ] **Bug #17 (bassa): il filtro blocca comandi legittimi quando `powershell` o `pwsh` compaiono come argomento**
  - **Verifica QA ciclo 5:** ancora presente: `test_encoded_filter_false_positive_cycle4` passa su entrambi i casi.
  - **File:** `engine/vault_engine/agent/tools.py` (`_uses_encoded_command`).
  - **Causa:** appena trova un token con nome `powershell`/`pwsh`, il filtro esamina **tutti** i token successivi, anche quando quel nome è un argomento di un altro cmdlet. In quel caso `-ea` è l'alias comunissimo di `-ErrorAction`.
  - **Come riprodurlo:** `Get-Process pwsh -ea SilentlyContinue` e `Stop-Process -Name powershell -ea 0` vengono rifiutati come "comandi codificati". Sonda: `test_encoded_filter_false_positive_cycle4`.
  - **Correzione proposta:**
    - considerare `powershell`/`pwsh` solo in **posizione di comando**: primo token di un segmento dopo `;`, `|`, `&&`, `||` o `&`, oppure `-FilePath`/primo argomento posizionale di `Start-Process`;
    - fermare la scansione degli argomenti al separatore di comando successivo.

- [ ] **Bug #18 (media): se il primo "Apri documento" fallisce, l'apertura resta bloccata fino al riavvio dell'app**
  - **Verifica QA ciclo 5:** ancora presente: `desktop/electron/main.cjs:199` usa ancora `supportedExtsPromise ??= engineFetch("/health")...` senza azzerare la cache in caso di errore.
  - **File:** `desktop/electron/main.cjs` (`supportedExtensions`).
  - **Causa:** `supportedExtsPromise ??= engineFetch("/health")...` memorizza anche una promessa **rifiutata**. Se la prima richiesta capita mentre il motore non è pronto o si sta riavviando, ogni apertura successiva fallisce subito senza riprovare.
  - **Effetti:** il messaggio "apertura consentita solo per i documenti supportati dei Vault" compare per qualunque documento finché non si chiude e riapre l'app.
  - **Come riprodurlo** (simulazione Node dello stesso schema): con un `engineFetch` che fallisce solo la prima volta, i tentativi 1, 2 e 3 falliscono tutti e `/health` viene chiamato una sola volta.
  - **Correzione proposta:** `engineFetch(...).then(...).catch((e) => { supportedExtsPromise = null; throw e; })`; in aggiunta, azzerare la cache quando il motore si riavvia.

### Miglioramenti

- [ ] **Miglioramento #13: segnalazioni di `ruff` e nessun test per la logica di apertura dei file**
  - **Verifica QA ciclo 5:** ancora aperto: `ruff` segnala ancora `F821 Any` in `providers.py` (righe 198 e 220) e `F401 Any` in `ollama_hub.py`. Altre segnalazioni nel Miglioramento #14.
  - **`providers.py`:** `F821 Undefined name 'Any'` alle righe 198 e 220, introdotto con `ensure_loaded(events: Any = None)`. Oggi funziona solo grazie a `from __future__ import annotations`; `typing.get_type_hints(ensure_loaded)` solleverebbe `NameError`.
  - **`ollama_hub.py`:** `F401 'typing.Any' imported but unused`.
  - **Proposta:** importare `Any` in `providers.py`, togliere l'import inutile e aggiungere `ruff check` ai controlli che si lanciano prima di ogni push.
  - **Test mancanti:** la logica di `assertOpenableTarget` (Miglioramento #8 e Bug #18) non ha test automatici. Spostarla in un modulo CommonJS senza dipendenze da Electron e testarla con `node --test`.

---

## Sonde QA del ciclo 5 (riproducibili)

Per eseguirle: salva il codice qui sotto in `engine/tests/_probe_qa5.py` (file temporaneo, da non committare) e lancia `uv run pytest -q tests/_probe_qa5.py` dalla cartella `engine`. Ogni test passa quando il difetto è presente: al ciclo 5 passano entrambi.

| Sonda | Voce |
|---|---|
| `test_hub_delete_raises_typeerror` | Bug #19 |
| `test_delete_route_answers_500` | Bug #19 |

I Bug #20 e #21 riguardano l'interfaccia React; i Bug #22-#25 gli script PowerShell di Workspace Harness. Si riproducono con i passi indicati nelle voci.

<details><summary>Codice delle sonde del ciclo 5</summary>

```python
"""Sonde QA ciclo 5: ciascun test PASSA se il difetto ipotizzato è presente."""
import asyncio

import pytest

from vault_engine import ollama_hub


def test_hub_delete_raises_typeerror():
    """Bug #19: httpx.AsyncClient.delete() non accetta json=; fallisce prima di contattare Ollama."""
    with pytest.raises(TypeError, match="unexpected keyword argument 'json'"):
        asyncio.run(ollama_hub.delete({"ollama": "http://127.0.0.1:9"}, "qualsiasi:latest"))


def test_delete_route_answers_500(monkeypatch):
    """Bug #19: la route cattura solo HubError, quindi il TypeError diventa un 500."""
    from fastapi.testclient import TestClient

    from vault_engine import app as appmod

    async def fake_unload(endpoints, model):
        return None

    monkeypatch.delenv("WSOS_TOKEN", raising=False)
    monkeypatch.setattr(ollama_hub, "unload", fake_unload)
    monkeypatch.setattr(appmod.state, "settings", type("S", (), {"get": lambda self: type("C", (), {"endpoints": {"ollama": "http://127.0.0.1:9"}})()})(), raising=False)
    client = TestClient(appmod.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    assert client.post("/ollama/delete", json={"model": "bge-m3:latest"}).status_code == 500
```

</details>

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

## Sonde QA del ciclo 4 (riproducibili)

Per eseguirle: salva il codice qui sotto in `engine/tests/_probe_qa4.py` (file temporaneo, da non committare) e lancia `uv run pytest -q tests/_probe_qa4.py` dalla cartella `engine`. Ogni test di difetto passa quando il difetto è presente: al ciclo 4 passano tutti e 5. `test_ipv6_loopback_host_now_accepted` invece è un controllo positivo e deve passare sempre.

| Sonda | Voce |
|---|---|
| `test_encoded_filter_bypass_cycle4` (3 casi) | Bug #16 |
| `test_encoded_filter_false_positive_cycle4` (2 casi) | Bug #17 |
| `test_ipv6_loopback_host_now_accepted` | verifica del Bug #15 (controllo positivo) |

Il Bug #18 riguarda Electron: si riproduce con la simulazione Node descritta nella voce stessa.

<details><summary>Codice delle sonde del ciclo 4</summary>

```python
"""Sonde QA ciclo 4: ciascun test PASSA se il difetto ipotizzato è presente."""
import pytest

from vault_engine.agent.tools import _uses_encoded_command


@pytest.mark.parametrize("cmd", [
    "Start-Process powershell -ArgumentList '-NoProfile -e SGVsbG8='",   # solo la prima parola è controllata
    "Start-Process powershell -ArgumentList '-NoProfile','-e','SGVsbG8='",  # lista separata da virgole = un token \S+
    "Start-Process powershell -ArgumentList @('-e','SGVsbG8=')",
])
def test_encoded_filter_bypass_cycle4(cmd):
    assert not _uses_encoded_command(cmd)


@pytest.mark.parametrize("cmd", [
    "Get-Process pwsh -ea SilentlyContinue",          # -ea = alias comune di -ErrorAction
    "Stop-Process -Name powershell -ea 0",
])
def test_encoded_filter_false_positive_cycle4(cmd):
    assert _uses_encoded_command(cmd)


def test_ipv6_loopback_host_now_accepted(monkeypatch):
    """Controllo positivo (deve PASSARE anche a difetto corretto): verifica del Bug #15."""
    from fastapi.testclient import TestClient
    from vault_engine import app as appmod
    monkeypatch.delenv("WSOS_TOKEN", raising=False)
    with TestClient(appmod.app, base_url="http://127.0.0.1") as c:
        assert c.get("/health", headers={"Host": "[::1]:8765"}).status_code == 200
        assert c.get("/health", headers={"Host": "attacker.example"}).status_code == 400
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
