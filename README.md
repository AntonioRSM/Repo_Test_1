# Workspace OS · RAG Vault Studio

Applicazione desktop per Windows 11 che trasforma cartelle di documenti in archivi RAG
(Vault) **interamente in locale**: parsing, OCR, chunking, embedding e vettori non lasciano
mai il PC. È il primo modulo del clone personalizzato di Perplexity Personal Computer:
l'agente arriverà dopo e userà i Vault come strumento di retrieval.

```
desktop/   Electron 33 + React 18 + Fluent UI v9 (Mica, tray, drag & drop)
engine/    Python 3.12: FastAPI su 127.0.0.1, LanceDB, PyMuPDF, RapidOCR-ONNX, watchdog
```

## Installazione rapida (Windows 11)

1. Scarica il progetto: `git clone -b workspace-os https://github.com/AntonioRSM/Repo_Test_1.git WorkspaceOS`
   (oppure il file ZIP del ramo, ma senza git l'aggiornamento automatico non è disponibile).
2. Doppio clic su **`INSTALLA.bat`**. Se mancano installa con `winget` **uv** (che scarica Python 3.12) e
   **Node.js LTS**, poi prepara il motore (`uv sync --no-build`) e compila l'interfaccia (`npm install`, `npm run build`).
3. Nel **menu Start** compare la cartella **RAG Vault Studio** con:
   - **RAG Vault Studio**: avvia l'app;
   - **Manuale RAG Vault Studio**: il manuale d'uso;
   - **Aggiorna RAG Vault Studio** (solo se la cartella è un clone git): `git pull` e reinstallazione.

Per aggiornare, chiudi prima l'app (anche dall'icona vicino all'orologio).

## Avvio

Prerequisiti: [uv](https://docs.astral.sh/uv/), Node.js 22+, LM Studio e/o Ollama con un
modello di embedding (es. `bge-m3`, `nomic-embed-text`).

```powershell
cd engine;  uv sync --no-build
cd ..\desktop;  npm install;  npm run build
npm run app            # oppure: start.cmd
```

`start.cmd` nella radice avvia l'app; `--hidden` la avvia direttamente nella tray
(è l'argomento usato dall'opzione "Avvia con Windows").

Sviluppo dell'interfaccia: `npm run dev` (Vite su :5173) e, in un altro terminale,
`npm run app:dev`. Per provarla in un browser senza Electron, avvia il motore con
`uv run python -m vault_engine --port 8765` e apri `http://localhost:5173/?port=8765`.

## Funzioni

| Area | Implementazione |
|---|---|
| Auto-discovery | Sonda LM Studio (`/api/v0/models`, fallback `/v1/models`) e Ollama (`/api/tags`, `/api/show` per le capability) su endpoint configurabili; ogni modello è classificato come embedding / LLM / vision e mostra se è caricato |
| Model Router | Embedding per Vault; LLM globale per riassunti contestuali, re-ranking e risposte RAG; modello vision per l'OCR. Le chiamate usano gli endpoint OpenAI-compatibili `/v1/embeddings` e `/v1/chat/completions`. I blocchi `<think>` dei modelli di ragionamento vengono rimossi |
| Hardware | CPU/RAM con psutil; GPU e VRAM dai contatori Windows "GPU Engine" e "GPU Adapter Memory" (Intel, AMD e NVIDIA) oppure da `nvidia-smi`; grafici live nella Dashboard |
| Formati | `.docx .xlsx .pptx .msg .pdf .png .jpg .jpeg .tif .tiff .bmp .webp .txt .md .json .csv`. I `.msg` includono gli allegati supportati |
| OCR | Le pagine PDF con meno testo della soglia vengono renderizzate a 200 dpi e passate all'OCR. Motori: RapidOCR ONNX (predefinito, con ricostruzione di righe, paragrafi e tabelle dai riquadri), Tesseract 5 (se installato) o un Vision LLM (llava, qwen2-vl, gemma…) |
| Parsing | Titoli DOCX dagli stili, titoli PDF da dimensione e grassetto del font, tabelle PDF (PyMuPDF `find_tables`) e Office in Markdown, rimozione di intestazioni e piè di pagina ripetuti. Parser Docling opzionale per i layout complessi (`uv sync --extra docling`) |
| Chunking | Ricorsivo (dimensione e overlap configurabili) o semantico (confine dove la distanza fra embedding a sinistra e a destra supera un percentile); entrambi rispettano le sezioni e conservano il percorso dei titoli e le pagine |
| Metadati | Percorso, nome, estensione, SHA-256, autore, titolo, date di creazione e modifica, lingua rilevata, pagine e pagine passate all'OCR |
| Vault | Più Vault indipendenti, ciascuno con la propria cartella `%LOCALAPPDATA%\WorkspaceOS\vaults\<id>` (config, manifest SQLite, LanceDB) |
| Sync incrementale | Un file viene rielaborato solo se cambiano dimensione o data e il nuovo SHA-256 è diverso; i file rimossi escono dall'indice. Il watcher (watchdog, debounce di 3 s) aggiorna in background; all'avvio un sync recupera le modifiche fatte ad app chiusa |
| Auditor | Elenco dei file con stato ed errori, chunk per documento, proiezione PCA 2D dei vettori, test di Search & Retrieval con cosine, dot product ed euclidea affiancati, re-ranking LLM opzionale e risposta RAG con citazioni |

## Agente (fase 2)

Pagina **Agente**: un ciclo agentico in stile Perplexity Personal Computer che gira
interamente su un modello locale (LM Studio/Ollama, tool calling compatibile OpenAI) e usa i
Vault come base di conoscenza.

| Strumento | Cosa fa | Rischio |
|---|---|---|
| `vault_search`, `list_vaults` | Ricerca semantica nei Vault scelti per la conversazione | lettura |
| `list_directory`, `read_file` | Elenca cartelle e legge file (Office, PDF con OCR, immagini, email, testo) | lettura |
| `write_file`, `edit_file` | Crea file di testo o sostituisce un testo esatto | scrittura |
| `run_powershell` | Esegue PowerShell 5.1 con timeout; i comandi codificati sono rifiutati | esecuzione |
| `web_search`, `fetch_url` | Ricerca su DuckDuckGo senza chiave e testo leggibile delle pagine | rete |
| `task_list` | Piano di lavoro mostrato nella chat | — |

- **Ogni azione richiede approvazione** nella chat: *Consenti*, *Consenti sempre in questa
  chat* (revocabile dal badge in alto) o *Nega*. Un rifiuto viene comunicato al modello con
  l'istruzione di non aggirarlo. Fa eccezione solo `task_list`, che aggiorna il piano
  visibile e non ha effetti sul PC.
- Risposte in streaming; budget di passi (predefinito 10), poi una risposta finale senza
  strumenti. Il contesto viene tagliato a un turno utente e privato delle chiamate rimaste
  senza risposta.
- Conversazioni salvate in `%LOCALAPPDATA%\WorkspaceOS\agent.sqlite`.
- Prima di ogni esecuzione il motore carica esplicitamente l'LLM e i modelli di embedding dei
  Vault (`/api/v1/models/load` di LM Studio), che restano così in memoria insieme. Su questo
  PC il primo passo è sceso da ~3 minuti a ~22 secondi.
- Tempi misurati con Gemma 4 E4B su CPU: domanda con PowerShell 44 s; ricerca web +
  scrittura file + risposta 3 min 20 s.
- Serve un modello addestrato per il tool calling. Fra quelli installati qui, solo
  `google/gemma-4-e4b` lo è (`trained_for_tool_use` di LM Studio).

## Sicurezza e privacy

- Il motore ascolta solo su `127.0.0.1`. Quando lo avvia l'app desktop, ogni richiesta
  richiede un token casuale generato a ogni avvio (`x-wsos-token`).
- L'eliminazione di un Vault cancella solo il suo indice; i documenti originali non
  vengono mai modificati.
- Il motore si chiude da solo se l'app che l'ha avviato termina (`WSOS_PARENT_PID`).

## Note per questo PC (Smart App Control attivo)

- `pyarrow` è fissato a una versione `<22`: la DLL `_dataset` della 26.0 non ha ancora
  reputazione e viene bloccata, e LanceDB non può caricarsi.
- Il motore non è un pacchetto installabile (`[tool.uv] package = false`) e si usa
  `uv sync --no-build`: le build PEP 517 girano in un interprete temporaneo che Smart App
  Control blocca. Per lo stesso motivo i `.msg` si leggono con `olefile` invece che con
  `extract-msg`.

## Modelli locali: comportamenti da conoscere

- **Modelli di ragionamento** (Gemma 4, Qwen 3, DeepSeek-R1…): per re-ranking, risposte
  RAG, riassunti e OCR vision il motore invia `reasoning_effort: "none"` (LM Studio) o
  `think: false` (Ollama). Con Gemma 4 E4B su CPU questo porta una richiesta da 95 s a 18 s
  ed evita che il budget di token si esaurisca prima della risposta. Se il server non
  conosce il parametro, la richiesta viene ripetuta senza.
- **Un solo modello in memoria** (JIT di LM Studio con auto-evict): l'ingestione lavora a
  ondate di 24 file, prima parsing e OCR per tutta l'ondata, poi gli embedding. Gli errori
  temporanei di caricamento ("Failed to load model… Operation canceled", 5xx, 429)
  vengono ritentati dopo 3, 10 e 20 secondi.
- **Senza GPU dedicata** l'LLM gira su CPU. Tempi misurati su questo PC (Intel UHD,
  16 GB): risposta RAG ~50 s, re-ranking di 8 passaggi ~2 min, OCR vision qualche minuto a
  pagina. RapidOCR resta molto più rapido per le scansioni pulite.

## Test

```powershell
cd engine
uv run pytest -m "not live"   # parser, OCR, chunking, pipeline con embedding finti
uv run pytest -m live         # embedding reali da LM Studio/Ollama
```
