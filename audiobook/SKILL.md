---
name: audiobook-f5tts
description: Genera audiolibri MP3 da capitoli .txt o .md italiani. LM Studio normalizza il testo (numeri arabi e romani, date, accenti sugli omografi) e lo divide in paragrafi; F5-TTS su Pinokio (Gradio /basic_tts) sintetizza la voce clonata; pydub unisce i segmenti con pause di 200 ms. Usala quando l'utente chiede di creare un audiolibro, leggere un capitolo o convertire file .txt o .md in audio/MP3.
version: 1.0.0
metadata:
  hermes:
    tags: [audiolibro, tts, f5-tts, lm-studio, pinokio, italiano, mp3]
---

# Audiolibri con LM Studio + F5-TTS (Pinokio)

## Dove sono i file

| Cosa | Windows | Da WSL2 (Hermes Agent) |
|---|---|---|
| Script e configurazione | `D:\Workspace\epub_build\audiobook\` | `/mnt/d/Workspace/epub_build/audiobook/` |
| Capitoli `.txt`/`.md` di input | `D:\Workspace\epub_build\testo_x_audio\` | `/mnt/d/Workspace/epub_build/testo_x_audio/` |
| MP3 generati | `D:\Workspace\epub_build\` | `/mnt/d/Workspace/epub_build/` |

Nel resto di questa skill `AUDIOBOOK_DIR` indica la cartella dello script.
I percorsi `D:\...` in `config.json` vengono convertiti in automatico in `/mnt/d/...` quando lo script gira in WSL.

## Procedura

1. **Verifica sempre i servizi prima di tutto** (LM Studio sulla 1234, F5-TTS cercato in automatico, voce di riferimento):
   ```bash
   cd AUDIOBOOK_DIR && python audiobook_pipeline.py --check
   ```
   Se un servizio è ❌, fermati e riporta all'utente il messaggio: non avviare il batch.
   - LM Studio: *Developer → Start Server* con un modello caricato.
   - F5-TTS: avvialo da Pinokio; la porta viene trovata da sola (`"f5_tts_url": "auto"`).

2. **Alla prima esecuzione o dopo aver cambiato modello LLM**, verifica la normalizzazione (niente audio):
   ```bash
   python audiobook_pipeline.py --test-normalizzazione
   ```
   Tutte le verifiche devono essere ✅. Se falliscono, suggerisci un modello più capace in LM Studio
   (es. Qwen3 8B/14B, Gemma 3 12B, Mistral Small) prima di procedere.

3. **Genera l'audio**:
   - un capitolo: `python audiobook_pipeline.py --file capitolo_01.txt`
   - tutti i capitoli della cartella di input: `python audiobook_pipeline.py`
   - solo testo normalizzato, per controllarlo: `python audiobook_pipeline.py --file capitolo_01.txt --dry-run`
     (il JSON dei paragrafi resta in `temp_segments/<capitolo>/paragrafi.json`)
   - rigenerare un capitolo già esportato: aggiungi `--force`
   - WAV invece di MP3: aggiungi `--format wav`

   La generazione è lunga (minuti per capitolo): esegui il comando in foreground con un timeout ampio
   o in background e controlla l'output. Se si interrompe, rilancia lo stesso comando: riprende dai
   segmenti già creati in `temp_segments/`.

4. **Riporta all'utente** i percorsi degli MP3 creati (righe `✅`) e gli eventuali avvisi `⚠️`
   (cifre residue, blocchi in cui l'LLM potrebbe aver tagliato testo).

## Regole

- Non modificare i parametri F5-TTS senza richiesta: `nfe_step 32`, `speed 0.95`, `cross_fade_duration 0.15`,
  `remove_silence false` (tassativo: conserva le pause della punteggiatura).
- Se l'utente segnala sibilanti metalliche imposta `"nfe_step": 48` in `config.json`.
- Se `voice_ref_text` è ancora il segnaposto, chiedi all'utente la trascrizione esatta di `voce_guida.wav`.
- Non cancellare i file `.txt`/`.md` di input.
