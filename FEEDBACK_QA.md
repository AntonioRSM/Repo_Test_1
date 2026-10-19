# FEEDBACK QA – ciclo 2

**Ambito:** commit `dbacb23..3df854b` sul branch `claude/workspace-os-installer` (PR #20):
- `5b64cbe`: fix dei 6 bug QA del ciclo 1;
- `7ec57c8`: gestione dei modelli Ollama;
- `3df854b`: carica/libera per i modelli solo-embedding.

**Esito iniziale:** NON APPROVATO — 7 bug e 6 miglioramenti aperti.

**Aggiornamento fase Developer (19/10/2026, sera): TUTTI i bug (#1-#7) e i miglioramenti (#1-#6) sono stati corretti, con sonde trasformate in test di regressione (asserzioni invertite). Suite: 124 passed, 1 deselected. Frontend ricompilato. Smoke test live superato (Host straniero → 400; delete di modello con '/' nel nome raggiunge Ollama correttamente; porta annunciata dal socket uvicorn). Tester: nuovo ciclo richiesto.**

**Suite di test (Linux, `uv run pytest`):** 70 passati, 1 saltato, 1 fallito.
- Il test fallito è `test_mcp.py::test_stdio_server_lifecycle_and_secrets`, che usa DPAPI e funziona solo su Windows. È atteso, non è una regressione.
- Il frontend compila: `npm run build` va a buon fine.

**Sonde QA:** 13 test scritti per riprodurre i difetti qui sotto. Tutti confermano il difetto. Lo script è riportato in fondo al file.

---

## Bug

- [x] **Bug #1 (alta): con Ollama spento, ricerca e domande rispondono con un errore 500 generico invece che con un messaggio chiaro**
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
  - **File:** `engine/vault_engine/ollama_hub.py` (`load`, introdotto da `3df854b`).
  - **Causa:** quando `/api/generate` risponde 400 "does not support generate", il nuovo tentativo su `/api/embed` invia solo `{"model", "input"}`, senza `keep_alive`.
  - **Effetti:** un modello come `bge-m3` caricato dalla pagina Modelli usa il valore predefinito di Ollama (5 minuti) invece di `ollama_keep_alive_minutes`, quindi esce dalla memoria prima del previsto.
  - **Come riprodurlo:**
    1. Imposta il tempo di residenza a 60 minuti.
    2. Carica `bge-m3` dalla pagina Modelli.
    3. In `/api/ps`, `expires_at` risulta a circa 5 minuti.
  - **Correzione proposta:** passare `"keep_alive": f"{keep_alive_minutes}m"` anche nel nuovo tentativo su `/api/embed` e aggiungere un'asserzione sul body in `test_ollama_hub.py`.

---

## Miglioramenti

- [x] **Miglioramento #1: non bloccare le richieste HTTP mentre un modello si scarica**
  - **File:** `app.py` (`retrieve`), `agent/runner.py` e `providers.py`.
  - **Problema:** con `ollama_auto_pull=True`, una semplice ricerca o domanda resta in attesa per tutto il download (diversi GB, anche decine di minuti), mentre il client va in timeout.
  - **Proposta:**
    - Nelle richieste interattive, non scaricare.
    - Rispondere subito 409/503 con "modello in download (vedi pagina Modelli)" e avviare il download in background con la stessa logica di deduplica di `_pulls`.

- [x] **Miglioramento #2: evitare download doppi dello stesso modello**
  - **File:** `providers.py` e `app.py`.
  - **Problema:** `_pulls` deduplica solo `/ollama/pull`. Più job di Vault diversi, l'agente o una ricerca possono avviare contemporaneamente il pull dello stesso modello.
  - **Proposta:** spostare il registro `_pulls` in `ollama_hub`, con un lock per modello, e usarlo anche da `ensure_loaded`.

- [x] **Miglioramento #3: limitare gli eventi di avanzamento del download**
  - **File:** `ollama_hub.py` (`pull`) e `app.py`.
  - **Problema:** viene inviato un evento SSE per **ogni** riga NDJSON di Ollama: per un modello da 20 GB sono migliaia al secondo verso il renderer, e React riaggiorna la pagina ogni volta. La sonda `test_pull_progress_event_flood` conta 10.000 eventi su 10.000 righe.
  - **Proposta:** al massimo 1 evento ogni 250–500 ms, oppure ogni +1%, più sempre i cambi di stato.

- [x] **Miglioramento #4: `list_directory` legge il disco sul thread principale del motore e il limite di 301 risultati non basta**
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
  - **File:** `desktop/src/pages/Models.tsx`.
  - **Problema:**
    - I nomi della libreria non hanno tag (`llama3.2`), quelli installati sì (`llama3.2:latest`).
    - `installedNames.has(m.name)` e `has(m.name.split(":")[0])` sono sempre falsi, quindi un modello installato mostra ancora "Scarica".
    - `description` non viene mai valorizzata dallo scraper, quindi la colonna resta vuota.
  - **Proposta:**
    - Calcolare l'insieme dei nomi installati senza tag.
    - Rimuovere `description` o estrarla dalla scheda del modello.

- [x] **Miglioramento #6: pulizia del codice e documentazione**
  - **Codice inutilizzato:** `ollama_hub.reconcile_loaded` e `ollama_hub.ensure_pulled` non hanno chiamanti in produzione. Inoltre `reconcile_loaded` riceve un parametro `keep_alive_minutes` che non usa. Integrarle (es. liberare RAM/VRAM dopo un job) oppure rimuoverle.
  - **Docstring di `ollama_hub`:** dice "nothing leaves the machine", ma `library_search` interroga `ollama.com` inviando la ricerca dell'utente. Correggere la docstring e segnalarlo nella pagina Modelli.
  - **`ollama_auto_pull` attivo per impostazione predefinita:** un nome di modello sbagliato nelle impostazioni avvia download di diversi GB senza conferma. Valutare il default `False` o una conferma nella UI.
  - **`_cors_origin_regex()`:** viene calcolata all'import del modulo. Va documentato che `WSOS_TOKEN` deve essere già impostato prima dell'import, cosa che oggi Electron garantisce.
  - **Download in corso alla chiusura del motore:** i task in `_pulls` non vengono annullati nello shutdown del `lifespan`. Annullarli insieme ai worker.

---

## Sonde QA (riproducibili)

Per eseguirle: salva il codice qui sotto in `engine/tests/_probe_qa.py` (file temporaneo, non da committare) e lancia `uv run pytest -q tests/_probe_qa.py -s` dalla cartella `engine`.

<details><summary>Codice delle sonde</summary>

```python
"""Sonde QA: ciascun test PASSA se il difetto ipotizzato è presente."""
import asyncio, os, time

import httpx
import pytest
from fastapi.testclient import TestClient

from vault_engine import ollama_hub, providers
from vault_engine.agent.tools import _uses_encoded_command, _list_directory
from vault_engine.config import ModelRef


def fake_ollama(tags, ps=None, pull_lines=None):
    def handler(req: httpx.Request):
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n, "size": 1} for n in tags]})
        if req.url.path == "/api/ps":
            return httpx.Response(200, json={"models": ps or []})
        if req.url.path == "/api/pull":
            return httpx.Response(200, text="\n".join(pull_lines or ['{"status":"success"}']))
        return httpx.Response(200, json={})
    return httpx.MockTransport(handler)


def patch_transport(monkeypatch, transport):
    orig = httpx.AsyncClient.__init__
    def init(self, *a, **kw):
        kw["transport"] = transport
        orig(self, *a, **kw)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)


def test_is_installed_false_positive_on_other_tag(monkeypatch):
    patch_transport(monkeypatch, fake_ollama(["llama3:8b"]))
    # "llama3" in Ollama significa "llama3:latest", che NON è installato
    assert asyncio.run(ollama_hub.is_installed({}, "llama3")) is True


def test_ensure_loaded_raises_when_ollama_offline(monkeypatch):
    def handler(req):
        raise httpx.ConnectError("refused")
    patch_transport(monkeypatch, httpx.MockTransport(handler))
    ref = ModelRef(provider="ollama", model="bge-m3")
    with pytest.raises(ollama_hub.HubError):
        asyncio.run(providers.ensure_loaded({}, [(ref, "embedding")]))


def test_ensure_loaded_pull_error_emits_no_error_event(monkeypatch):
    patch_transport(monkeypatch, fake_ollama([], pull_lines=['{"error":"file does not exist"}']))
    seen = []
    class Ev:
        def publish(self, e): seen.append(e)
    ref = ModelRef(provider="ollama", model="nonexistent-model")
    with pytest.raises(ollama_hub.HubError):
        asyncio.run(providers.ensure_loaded({}, [(ref, "llm")], events=Ev()))
    statuses = [e["status"] for e in seen]
    assert statuses == ["download_avviato"]  # nessun evento "errore": la UI resta bloccata


def test_delete_route_rejects_namespaced_models(monkeypatch):
    from vault_engine import app as appmod
    monkeypatch.delenv("WSOS_TOKEN", raising=False)
    called = []
    async def fake(endpoints, name): called.append(name)
    monkeypatch.setattr(ollama_hub, "unload", fake)
    monkeypatch.setattr(ollama_hub, "delete", fake)
    with TestClient(appmod.app) as c:
        r = c.delete("/ollama/models/hf.co%2Fbartowski%2FQwen:Q4_K_M")
    assert r.status_code == 404 and called == []


@pytest.mark.parametrize("cmd", [
    "powershell /enc SGVsbG8=",
    "powershell /e SGVsbG8=",
    "powershell –e SGVsbG8=",          # en-dash, accettato da PowerShell
    "powershell '-e' SGVsbG8=",             # argomento quotato: PowerShell lo passa come -e
])
def test_encoded_filter_bypass(cmd):
    assert not _uses_encoded_command(cmd)


@pytest.mark.parametrize("cmd", [
    'node -e "console.log(1)"',
    "Get-Content f.txt -Enc UTF8",
    "Select-String -Path *.log -E 'x'",
])
def test_encoded_filter_false_positive(cmd):
    assert _uses_encoded_command(cmd)


def test_list_directory_sparse_pattern_walks_whole_tree(tmp_path):
    for i in range(300):
        d = tmp_path / f"d{i}"
        d.mkdir()
        for j in range(30):
            (d / f"f{j}.txt").write_text("x")
    class Ctx: pass
    t = time.perf_counter()
    out = asyncio.run(_list_directory(Ctx(), {"path": str(tmp_path), "pattern": "**/*.nessuno"}))
    elapsed = time.perf_counter() - t
    assert out["entries"] == []
    print(f"scansione completa di 9000 file senza risultati: {elapsed*1000:.0f} ms, sul thread dell'event loop")


def test_pull_progress_event_flood(monkeypatch):
    lines = [f'{{"status":"pulling","completed":{i},"total":10000}}' for i in range(10000)]
    patch_transport(monkeypatch, fake_ollama([], pull_lines=lines))
    n = []
    async def prog(p): n.append(p)
    asyncio.run(ollama_hub.pull({}, "m", prog))
    assert len(n) == 10000  # un evento SSE per ogni riga NDJSON, nessun throttling
```

</details>

Ogni test passa quando il difetto è presente: 13 passati su 13 al ciclo 2, anche dopo `3df854b`.

| Sonda | Difetto |
|---|---|
| `test_is_installed_false_positive_on_other_tag` | Bug #3 |
| `test_ensure_loaded_raises_when_ollama_offline` | Bug #1 |
| `test_ensure_loaded_pull_error_emits_no_error_event` | Bug #2 |
| `test_delete_route_rejects_namespaced_models` | Bug #4 |
| `test_encoded_filter_bypass` (4 casi) e `test_encoded_filter_false_positive` (3 casi) | Bug #5 |
| `test_list_directory_sparse_pattern_walks_whole_tree` | Miglioramento #4 |
| `test_pull_progress_event_flood` | Miglioramento #3 |

Quando un bug viene corretto, la sonda corrispondente va trasformata in test di regressione con l'asserzione invertita.


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
