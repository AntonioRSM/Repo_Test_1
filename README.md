# F5-TTS + LM Studio (Pinokio)

Script [Pinokio](https://pinokio.co) che:

1. **rileva l'hardware** del PC (GPU NVIDIA/AMD/Apple, VRAM, RAM) e sceglie il modello F5-TTS più adatto;
2. installa **F5-TTS** con la versione di PyTorch giusta per la tua GPU;
3. lo **collega a LM Studio** in due modi:
   - **interfaccia web**: chatti con l'LLM caricato in LM Studio e ogni risposta viene letta ad alta voce (file `.wav`);
   - **server MCP**: dentro la chat di LM Studio l'LLM ha lo strumento `text_to_speech` e può creare file audio da solo.

## Quale modello F5-TTS viene scelto

| Lingua | Modello | Note |
|---|---|---|
| `it` (default) | [`alien79/F5-TTS-italian`](https://huggingface.co/alien79/F5-TTS-italian) (architettura F5TTS_Base) | fine-tuning italiano elencato nei modelli condivisi ufficiali di F5-TTS |
| `en` / `zh` | `F5TTS_v1_Base` (SWivid) | modello ufficiale più recente |

Tutti i modelli F5 hanno la stessa dimensione (~336M parametri, ~1,3 GB), quindi l'hardware decide **dove** e **come** gira il modello, non quale variante usare:

| Hardware rilevato | Device | `nfe_step` | Note |
|---|---|---|---|
| NVIDIA ≥ 6 GB VRAM | `cuda` | 32 | qualità piena, GPU condivisibile con LM Studio |
| NVIDIA 3–6 GB | `cuda` | 32 | in LM Studio usa un LLM piccolo (3-4B Q4) o offload parziale |
| NVIDIA < 3 GB / nessuna GPU | `cpu` | 16 | circa 2 volte più veloce su CPU, qualità leggermente inferiore |
| Apple Silicon | `mps` | 32 | |

Il risultato viene salvato in `app/config.json` (modificabile a mano) ed è mostrato nella barra in cima all'interfaccia.

> ⚠️ I modelli F5-TTS sono rilasciati con licenza **CC-BY-NC-4.0** (solo uso non commerciale).

## Installazione

1. Installa [Pinokio](https://pinokio.co) e [LM Studio](https://lmstudio.ai).
2. In Pinokio: **Discover → Download from URL** e incolla l'URL di questo repository (oppure clonalo in `pinokio/api/`).
3. Premi **Installa**. Alla fine viene chiesta la lingua (`it`/`en`/`zh`) e viene rilevato l'hardware.

### Dove si trova "Avvia"

Dopo l'installazione, nella home di Pinokio clicca sulla scheda dell'app **F5-TTS + LM Studio**:
a sinistra compare il menu dell'app con **Avvia** (icona di accensione) in cima.
Se vedi ancora "Installa", l'installazione non è terminata o non è riuscita (controlla il terminale).
Dopo l'avvio, quando nel terminale compare `Running on local URL: http://127.0.0.1:…`,
la voce di menu diventa **Apri interfaccia**.

Per rifare la rilevazione o cambiare lingua usa **Rileva hardware / cambia lingua**.

## Collegamento a LM Studio

### A. Interfaccia web (LM Studio → voce)

1. In LM Studio carica un modello (es. Qwen3 4B, Gemma 3 4B, Llama 3.1 8B) e vai su **Developer → Start Server** (porta `1234`).
2. In Pinokio premi **Verifica LM Studio**, poi **Avvia** → **Apri interfaccia**.
3. Scheda *Chat con LM Studio*: scrivi un messaggio, la risposta viene generata dall'LLM e riprodotta con F5-TTS.
   Scheda *Testo → audio*: incolli un testo e scarichi il `.wav`.

I file vengono salvati in `app/output/`. Indirizzo, modello e prompt di sistema si cambiano in `app/config.json`
(`lmstudio_url`, `lmstudio_model` (vuoto = primo modello caricato), `system_prompt`) o con la variabile d'ambiente `LMSTUDIO_URL`.

### B. Server MCP (voce dentro la chat di LM Studio)

1. In Pinokio premi **Config MCP per LM Studio**: stampa un blocco JSON con i percorsi corretti del tuo PC.
2. In LM Studio: scheda **Program → Install → Edit mcp.json**, incolla il blocco dentro `mcpServers` e salva.
3. In chat abilita lo strumento `f5-tts` e chiedi ad esempio: *"Leggi ad alta voce questo testo: …"*. L'LLM chiamerà `text_to_speech` e ti dirà dove si trova il file `.wav`.

Serve un modello con supporto ai *tool* (es. Qwen3, Llama 3.1+, Mistral).

## Clonazione della voce

F5-TTS imita una voce di riferimento. Senza voce di riferimento viene usato l'esempio inglese incluso in F5-TTS:
per un italiano naturale carica nell'interfaccia 5–12 secondi di parlato italiano pulito con la sua trascrizione
(oppure imposta `ref_audio` e `ref_text` in `app/config.json`, così li usa anche il server MCP).
Se la trascrizione è vuota viene generata automaticamente con Whisper.

Per rendere una voce **predefinita** (usata anche dal server MCP) hai due modi:
- nell'interfaccia, *Voce di riferimento* → carica il file → **Salva come voce predefinita**;
- copia un file WAV in `app/voices/voce_riferimento.wav`.

La cartella `app/voices/` è esclusa da git: le registrazioni vocali non finiscono nel repository.
Usa solo voci di persone che hanno dato il consenso.

## Riga di comando

```bash
cd app
python tts_bridge.py --check                   # LM Studio è raggiungibile?
python tts_bridge.py --say "Buongiorno a tutti"
python tts_bridge.py --ask "Raccontami una curiosità su Roma" --out roma.wav
```

## File

| File | Scopo |
|---|---|
| `pinokio.js`, `install.js`, `start.js`, `torch.js`, `detect.js`, `check.js`, `mcp.js`, `update.js`, `reset.js` | script Pinokio |
| `app/detect_hardware.py` | rilevazione hardware e scelta del modello, scrive `config.json` |
| `app/tts_bridge.py` | client LM Studio (API compatibile OpenAI) + sintesi F5-TTS |
| `app/web_ui.py` | interfaccia Gradio chat → voce |
| `app/mcp_server.py`, `app/lmstudio_mcp_config.py` | server MCP per LM Studio e generatore della configurazione |

## Audiolibri (LM Studio + F5-TTS + Hermes Agent)

La cartella [`audiobook/`](audiobook/README.md) contiene la pipeline che trasforma capitoli `.txt` in MP3:
LM Studio normalizza il testo, F5-TTS (Gradio su Pinokio) genera la voce, pydub unisce i paragrafi.
Include la skill per Hermes Agent (`audiobook/SKILL.md`) e un piano di test.
