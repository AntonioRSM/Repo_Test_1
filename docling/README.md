# Docling – conversione archivi documentali per LightRAG

Converte in **Markdown pulito** tutti i documenti di un progetto, pronti per l'indicizzazione in LightRAG.
Gira in **WSL2** (Ubuntu) su Windows.

| Formato | Come viene gestito |
|---|---|
| PDF nativi | testo estratto direttamente, tabelle ricostruite |
| PDF scansionati, immagini (JPG, PNG, TIFF…) | OCR con Tesseract **italiano + inglese**; se il risultato è scarso, riprova con OCR su tutta la pagina |
| DOCX, PPTX, XLSX, ODT/ODS/ODP, RTF, HTML, EPUB, CSV | conversione diretta |
| DOC, XLS, PPT (vecchi Office) | conversione tramite LibreOffice |
| Email `.eml` / `.msg` | corpo + mittente/destinatari/data/oggetto; gli **allegati** vengono estratti e convertiti a loro volta |

## Installazione (una volta sola)

1. In PowerShell come amministratore, se WSL2 non è ancora installato:
   ```powershell
   wsl --install -d Ubuntu
   ```
2. Apri il terminale **Ubuntu**, vai nella cartella `docling` di questo repository e lancia:
   ```bash
   bash installa_wsl.sh
   ```
   Installa Python, Tesseract (ita+eng), LibreOffice, PyTorch (con CUDA se in WSL è visibile una GPU NVIDIA),
   Docling e i suoi modelli, e crea il comando `converti-archivio`.

## Struttura di un progetto

```
D:\RAG\progetto-alfa\
 ├─ originali\     ← metti qui i documenti (anche in sottocartelle)
 ├─ markdown\      ← creato dallo script: tutti i Markdown + registro + quarantena
 └─ inputs\        ← creato dallo script: solo i Markdown validi, da far leggere a LightRAG
```

## Uso

**Da Windows:** trascina la cartella del progetto su `converti_archivio.bat`
(oppure `converti_archivio.bat "D:\RAG\progetto-alfa"`).

**Da Ubuntu/WSL:**
```bash
converti-archivio /mnt/d/RAG/progetto-alfa
converti-archivio /mnt/d/RAG/progetto-alfa --ocr easyocr      # motore OCR alternativo
converti-archivio /mnt/d/RAG/progetto-alfa --timeout 1800     # documenti molto lunghi
```

## Cosa trovi in `markdown\`

- `<nome file>.<estensione>.md`: un Markdown per ogni documento, con in testa titolo, tipo, file originale, data e pagine
  (servono a LightRAG come contesto e per risalire all'originale).
- `registro_conversione.csv` (separatore `;`, si apre con Excel): esito di ogni file.

  | Esito | Significato |
  |---|---|
  | `OK` | convertito |
  | `OK_OCR_FORZATO` | convertito dopo un secondo passaggio OCR |
  | `PARZIALE` | alcune pagine non convertite (timeout o pagine illeggibili) |
  | `DA_VERIFICARE` | poco testo o testo illeggibile: **non** viene copiato in `inputs\`, controllalo a mano |
  | `ERRORE` | file danneggiato o protetto da password: copiato in `_quarantena\` |
  | `SALTATO` | allegato di un formato non supportato (es. firme `.p7s`) |
- `_quarantena\`: copie dei file che non si sono potuti convertire.
- `_allegati_estratti\`: allegati estratti dalle email.

## Ripresa e aggiornamenti

Lo script ricorda cosa ha già convertito (`markdown\.stato_conversione.json`). Se lo interrompi (Ctrl+C,
riavvio del PC) o aggiungi nuovi documenti, rilancialo: converte solo i file nuovi o modificati e ritenta
quelli andati in errore.

## Consigli

- **Non lanciare la conversione mentre LightRAG indicizza**: OCR e LLM si contendono GPU e RAM.
  Prima converti tutto, poi indicizza.
- Prima del carico completo, prova su 50–100 documenti rappresentativi e apri alcuni Markdown accanto agli
  originali, in particolare tabelle e scansioni.
- Le cartelle su `D:\` (viste da WSL come `/mnt/d/...`) sono più lente del disco interno di WSL,
  ma per qualche migliaio di documenti la differenza è accettabile.
