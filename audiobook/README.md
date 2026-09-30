# Audiolibri: LM Studio + F5-TTS (Pinokio) + Hermes Agent

Trasforma i capitoli `.txt` e `.md` di `D:\Workspace\epub_build\testo_x_audio` in MP3 (192 kbps) salvati in `D:\Workspace\epub_build`.

```
capitolo_01.txt ──► LM Studio :1234 ──► ["paragrafo 1", "paragrafo 2", ...]   (numeri, romani, date, accenti)
                                          │
                     F5-TTS Pinokio (porta trovata da sola) /basic_tts  ──► 001_paragrafo.wav, 002_paragrafo.wav ...
                                          │
                     pydub + 200 ms di silenzio ──► D:\Workspace\epub_build\capitolo_01.mp3
```

## File

| File | Scopo |
|---|---|
| `audiobook_pipeline.py` | script orchestratore |
| `config.json` | cartelle, URL, parametri LLM e F5-TTS |
| `SKILL.md` | skill per Hermes Agent |
| `test_normalizzazione.txt` | testo di prova con numeri arabi, romani, date e omografi |
| `tests/test_pipeline.py` | test offline (nessun servizio reale richiesto) |
| `voce_guida.wav` | **da aggiungere tu**: 6-10 s di parlato italiano pulito (escluso da git) |
| `temp_segments/` | segmenti WAV intermedi e `paragrafi.json` (cancellati dopo l'export) |

## Installazione (Windows)

1. Copia questa cartella in `D:\Workspace\epub_build\audiobook\`.
2. Dipendenze (Python 3.10+):
   ```bat
   cd /d D:\Workspace\epub_build\audiobook
   python -m pip install -r requirements.txt
   ```
3. **FFmpeg** serve per l'MP3: `winget install Gyan.FFmpeg`, oppure indica il percorso di `ffmpeg.exe` in `config.json` → `ffmpeg_path`.
4. Metti `voce_guida.wav` nella cartella e scrivi in `config.json` → `voice_ref_text` la sua **trascrizione esatta**.
5. Avvia **LM Studio** → *Developer* → *Start Server* (porta 1234) con un modello caricato.
   Consigliati: Qwen3 8B/14B, Gemma 3 12B, Mistral Small (i modelli da 3-4B sbagliano spesso le regole).
6. Avvia **F5-TTS** in Pinokio. Nel terminale di Pinokio leggi la riga `Running on local URL: http://127.0.0.1:XXXX`:
   Non serve annotare la porta: con `"f5_tts_url": "auto"` la pipeline cerca da sola il server Gradio con `/basic_tts`
   sulle porte 7860-7880 e 42000-42300 (`f5_tts_porte`), perché Pinokio la cambia a ogni avvio.
   Se trova solo l'interfaccia "F5-TTS + LM Studio" di questo repo (senza `/basic_tts`) lo segnala.

## Hermes Agent

Hermes Agent su Windows gira in WSL2: lo script converte da solo `D:\...` in `/mnt/d/...`.

```bash
mkdir -p ~/.hermes/skills/audiobook-f5tts
cp /mnt/d/Workspace/epub_build/audiobook/SKILL.md ~/.hermes/skills/audiobook-f5tts/
# dipendenze anche nel Python di WSL
python3 -m pip install -r /mnt/d/Workspace/epub_build/audiobook/requirements.txt
sudo apt install ffmpeg
```

Poi, in chat con Hermes (o in modalità one-shot, es. `hermes chat -q "..."`; controlla `hermes --help` per la tua versione):

> Genera l'audiolibro dal capitolo_01.txt usando LM Studio e F5-TTS su Pinokio

**Rete WSL ↔ Windows:** LM Studio e Pinokio girano su Windows. Se da WSL `localhost:1234` non risponde:
- attiva il *mirrored networking* (`%UserProfile%\.wslconfig` → `[wsl2]` `networkingMode=mirrored`, poi `wsl --shutdown`), **oppure**
- in LM Studio abilita *Serve on Local Network* e imposta in `config.json` l'IP di Windows
  (`ip route | awk '/default/ {print $3}'` da WSL). F5-TTS ascolta solo su 127.0.0.1: con questa seconda strada
  va avviato con `--host 0.0.0.0`, quindi il mirrored networking è la soluzione più semplice.

## Dalla chat di LM Studio (MCP)

Il server MCP del repo (`app/mcp_server.py`) ha gli strumenti `verifica_audiolibro`, `genera_audiolibro` e `stato_audiolibro`:
configuralo come descritto nel [README principale](../README.md#b-server-mcp-voce-dentro-la-chat-di-lm-studio), poi in chat:

> Chiama verifica_audiolibro

> Genera l'audiolibro di capitolo_01.txt

> A che punto è l'audiolibro?

Lo strumento avvia lo script in background e risponde subito (una chiamata MCP non può durare ore);
il log è in `app/output/audiolibro.log`. Chiudere LM Studio può interrompere la generazione:
rilanciandola riprende dai segmenti già creati.

## Uso diretto

```bat
python audiobook_pipeline.py --check                     :: LM Studio, F5-TTS (porta trovata da sola) e voce
python audiobook_pipeline.py --test-normalizzazione      :: verifica regole LLM, niente audio
python audiobook_pipeline.py --file capitolo_01.txt --dry-run   :: solo testo normalizzato
python audiobook_pipeline.py --file capitolo_01.txt      :: un capitolo
python audiobook_pipeline.py                             :: tutti i .txt e .md di testo_x_audio
```

Opzioni: `--force` (rigenera capitoli già esportati), `--format wav`, `--input-dir`, `--output-dir`, `--config`.
Se il batch si interrompe, rilancialo: riusa `paragrafi.json` e i segmenti già generati.

## Piano di test passo-passo

| # | Comando | Esito atteso |
|---|---|---|
| 1 | `python -m pip install pytest && python -m pytest tests -v` | tutti i test verdi (non servono LM Studio né F5-TTS) |
| 2 | `python audiobook_pipeline.py --check` | ✅ LM Studio con il nome del modello, ✅ F5-TTS, nessun ❌ sulla voce |
| 3 | `python audiobook_pipeline.py --test-normalizzazione` | 13/13 verifiche superate (vedi sotto) |
| 4 | copia `test_normalizzazione.txt` in `testo_x_audio\prova.txt`, poi `python audiobook_pipeline.py --file prova.txt --dry-run` | `temp_segments\prova\paragrafi.json` contiene il testo normalizzato |
| 5 | `python audiobook_pipeline.py --file prova.txt` | `D:\Workspace\epub_build\prova.mp3`; ascoltalo: numeri letti per esteso, pause naturali tra i paragrafi |
| 6 | batch completo: `python audiobook_pipeline.py` | un MP3 per ogni `.txt`/`.md`; riga finale `Completati N/N capitoli` |

Verifiche del passo 3 sul testo di prova:

| Input | Atteso |
|---|---|
| `28 libri`, `100 euro` | `ventotto libri`, `cento euro` |
| `1° posto`, `2° gara` | `primo posto`, `seconda gara` |
| `15/05/1998` | `quindici maggio millenovecentonovantotto` |
| `XIX secolo` | `diciannovesimo secolo` |
| `Luigi XIV`, `Pio IX` | `Luigi Quattordicesimo`, `Pio Nono` |
| `Capitolo IV, Volume II` | `Capitolo quarto, volume secondo` |
| tutto il testo | nessuna cifra araba né numero romano residuo, output = array JSON di stringhe |

Gli accenti sugli omografi (*àncora/ancóra*, *sùbito*, *princìpi*) vanno controllati a occhio nel testo stampato:
dipendono dal contesto e non hanno una forma unica verificabile in automatico.

## Note sui parametri

- **Pre-elaborazione senza LLM** (prima di LM Studio): dai file `.md` viene tolta la sintassi Markdown
  (titoli `#` → frase con punto, `**grassetto**`, link, immagini, note `[^1]`, codice, HTML) e i numeri romani
  inequivocabili diventano ordinali: `XIII secolo` → *tredicesimo secolo*, `XIX sec.` → *diciannovesimo secolo*,
  `Capitolo IV` → *Capitolo quarto*, `Parte II` → *Parte seconda* (anche Volume, Libro, Tomo, Canto, Atto, Scena, Sezione).
  Così i modelli piccoli non sbagliano più i secoli (es. *zerosimo*). `I` resta com'è quando è l'articolo
  (*I secoli bui*, *nel capitolo I personaggi*). Sovrani e papi (`Luigi XIV`, `Pio IX`) restano all'LLM.

- **`temperature` (0,65) non esiste in F5-TTS**: è un modello *flow-matching* e l'endpoint `/basic_tts` non ha
  questo parametro. Lo script legge i parametri dichiarati dal server e lo passa solo se presente (in un fork
  che lo supporta); altrimenti lo ignora e lo segnala. La stabilità del timbro è data da `seed` fisso
  (`randomize_seed = False`), così tutti i paragrafi hanno la stessa voce.
- `nfe_step`: 32 (48 se senti sibilanti metalliche), `speed` 0,95, `cross_fade_duration` 0,15,
  `remove_silence` **false**.
- L'LLM usa `llm_temperature` 0,1 (fedeltà al testo) e riceve il capitolo a blocchi di `llm_chunk_words` parole,
  per non superare il contesto del modello. Se un blocco normalizzato ha meno dell'85 % delle parole originali
  lo script avvisa: l'LLM potrebbe aver riassunto.
- Per usare l'output strutturato di LM Studio (`llm_json_schema: true`) il modello riceve lo schema
  `{"paragrafi": [...]}`; se non lo supporta lo script riprova senza schema e accetta anche un array JSON semplice.
- Con modelli che “pensano” (Qwen3) il blocco `<think>` viene ignorato; se la risposta si tronca aumenta `llm_max_tokens`
  o riduci `llm_chunk_words`.

> ⚠️ Usa solo voci di persone che hanno dato il consenso. I modelli F5-TTS sono rilasciati con licenza CC-BY-NC-4.0.
