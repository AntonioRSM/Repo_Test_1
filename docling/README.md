# Docling – conversione archivi documentali per LightRAG

Converte in **Markdown pulito** tutti i documenti di un progetto, pronti per l'indicizzazione in LightRAG.
Funziona direttamente su **Windows 11** (avvio dal menu Start); in alternativa anche in WSL2.

| Formato | Come viene gestito |
|---|---|
| PDF nativi | testo estratto direttamente, tabelle ricostruite |
| PDF scansionati, immagini (JPG, PNG, TIFF…) | OCR con **RapidOCR** (lettere accentate, €, tabelle); se il risultato è scarso, riprova con OCR su tutta la pagina |
| DOCX, PPTX, XLSX, ODT/ODS/ODP, RTF, HTML, EPUB, CSV | conversione diretta |
| DOC, XLS, PPT (vecchi Office) | conversione tramite LibreOffice |
| Email `.eml` / `.msg` | corpo + mittente/destinatari/data/oggetto; gli **allegati** vengono estratti e convertiti a loro volta |

## Installazione su Windows 11 (una volta sola)

1. Scarica questa cartella `docling` sul PC.
2. Apri la sottocartella `windows` e fai **doppio clic su `INSTALLA.bat`**.
   Windows può chiedere più volte l'autorizzazione (per Python, Tesseract e LibreOffice): rispondi **Sì**.
3. Attendi la fine (la prima volta 10–30 minuti: scarica alcuni GB fra PyTorch e i modelli).

L'installatore:
- installa con `winget`, se mancano, **Python 3.12**, **LibreOffice** e **Tesseract OCR** (motore alternativo, con dizionari italiano e inglese);
- crea un ambiente Python dedicato con **Docling**, l'OCR **RapidOCR** e **PyTorch** (con CUDA se trova una GPU NVIDIA);
- scarica i modelli di Docling;
- crea nel **menu Start** la cartella **Docling Archivio** con:
  - **Converti archivio documentale**: avvia la conversione;
  - **Leggimi**: queste istruzioni;
  - **Disinstalla Docling Archivio**.

Tutto viene installato in `%LOCALAPPDATA%\DoclingArchivio` (i modelli in `%USERPROFILE%\.cache\docling`).

## Struttura di un progetto

```
D:\RAG\progetto-alfa\
 ├─ originali\     ← metti qui i documenti (anche in sottocartelle)
 ├─ markdown\      ← creato dal programma: tutti i Markdown + registro + quarantena
 └─ inputs\        ← creato dal programma: solo i Markdown validi, da far leggere a LightRAG
```

## Uso

1. Menu Start → **Converti archivio documentale**.
2. Scegli la cartella del progetto (es. `D:\RAG\progetto-alfa`). Se manca `originali`, il programma
   propone di crearla e la apre in Esplora file.
3. La conversione procede nella finestra; alla fine si apre la cartella `markdown` e ti viene proposto di
   aprire il registro in Excel.

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
- Tieni i percorsi brevi (es. `D:\RAG\progetto`): Windows ha problemi oltre i 260 caratteri, a meno che
  l'installatore sia stato eseguito come amministratore (abilita i percorsi lunghi).

## Uso da riga di comando (avanzato)

```powershell
& "$env:LOCALAPPDATA\DoclingArchivio\env\Scripts\python.exe" "$env:LOCALAPPDATA\DoclingArchivio\app\converti.py" `
    D:\RAG\progetto-alfa\originali D:\RAG\progetto-alfa\markdown --copia-in D:\RAG\progetto-alfa\inputs
```

Opzioni utili: `--ocr tesseract` (motore OCR alternativo), `--timeout 1800` (documenti molto lunghi).

## Alternativa: WSL2 (Ubuntu)

Se preferisci lavorare in WSL2: dal terminale Ubuntu lancia `bash installa_wsl.sh`, poi
`converti-archivio /mnt/d/RAG/progetto-alfa`, oppure trascina la cartella del progetto su `converti_archivio.bat`.
