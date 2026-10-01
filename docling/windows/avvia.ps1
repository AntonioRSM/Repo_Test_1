# Avvio dal menu Start: sceglie la cartella del progetto e converte i documenti con Docling.
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$Host.UI.RawUI.WindowTitle = 'Docling Archivio - conversione documenti'

$Base   = Join-Path $env:LOCALAPPDATA 'DoclingArchivio'
$Config = Get-Content (Join-Path $Base 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$Ultima = Join-Path $Base 'ultima_cartella.txt'

# finestra invisibile "sempre in primo piano": tiene dialoghi e messaggi davanti alla console
$Primo = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true; ShowInTaskbar = $false }

function Messaggio($testo, $pulsanti = 'OK', $icona = 'Information') {
    [System.Windows.Forms.MessageBox]::Show($Primo, $testo, 'Docling Archivio', $pulsanti, $icona)
}

# ---------------------------------------------------------------- scelta della cartella
$dlg = New-Object System.Windows.Forms.FolderBrowserDialog
$dlg.Description = "Scegli la cartella del PROGETTO (es. D:\RAG\progetto-alfa).`nDeve contenere la sottocartella 'originali' con i documenti."
$dlg.ShowNewFolderButton = $true
if (Test-Path $Ultima) { $dlg.SelectedPath = (Get-Content $Ultima -Raw -Encoding UTF8).Trim() }
if ($dlg.ShowDialog($Primo) -ne 'OK') { exit 0 }
$Progetto = $dlg.SelectedPath
Set-Content $Ultima $Progetto -Encoding UTF8

# se l'utente ha scelto direttamente 'originali', risale al progetto
if ((Split-Path $Progetto -Leaf) -ieq 'originali') { $Progetto = Split-Path $Progetto -Parent }
$Originali = Join-Path $Progetto 'originali'
$Markdown  = Join-Path $Progetto 'markdown'
$Inputs    = Join-Path $Progetto 'inputs'

if (-not (Test-Path $Originali)) {
    $r = Messaggio "La cartella`n$Progetto`nnon contiene la sottocartella 'originali'.`n`nVuoi crearla adesso? Si aprirà in Esplora file: copiaci i documenti e poi riavvia la conversione." 'YesNo' 'Question'
    if ($r -eq 'Yes') {
        New-Item -ItemType Directory -Force -Path $Originali | Out-Null
        Start-Process explorer.exe $Originali
    }
    exit 0
}

# ---------------------------------------------------------------- ambiente
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:TESSDATA_PREFIX = $Config.tessdata
if ($Config.soffice)   { $env:DOCLING_LIBREOFFICE_CMD = $Config.soffice }
if ($Config.tesseract) { $env:TESSERACT_CMD = $Config.tesseract }
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host '=====================================================' -ForegroundColor Green
Write-Host '  Docling Archivio - conversione documenti' -ForegroundColor Green
Write-Host '=====================================================' -ForegroundColor Green
Write-Host "Progetto : $Progetto"
Write-Host "Originali: $Originali"
Write-Host "Risultati: $Markdown"
Write-Host "LightRAG : $Inputs"
Write-Host "`nPuoi chiudere la finestra in qualsiasi momento: al prossimo avvio riprende da dove si è fermato.`n" -ForegroundColor Yellow

$inizio = Get-Date
& $Config.python (Join-Path $Base 'app\converti.py') $Originali $Markdown --copia-in $Inputs
$codice = $LASTEXITCODE
$durata = (Get-Date) - $inizio

# ---------------------------------------------------------------- riepilogo
$Registro = Join-Path $Markdown 'registro_conversione.csv'
$daControllare = 0
if (Test-Path $Registro) {
    $daControllare = @(Import-Csv $Registro -Delimiter ';' -Encoding UTF8 |
        Where-Object { $_.data -ge $inizio.ToString('yyyy-MM-dd HH:mm:ss') -and $_.esito -in 'ERRORE', 'DA_VERIFICARE', 'PARZIALE', 'ERRORE_ALLEGATI' }).Count
}

$testo = "Conversione terminata in {0:hh\:mm\:ss}.`n`n" -f $durata
if ($codice -ne 0) { $testo = "La conversione si è interrotta con un errore (codice $codice).`nControlla i messaggi nella finestra.`n`n" }
if ($daControllare -gt 0) { $testo += "$daControllare file da controllare (ERRORE / DA_VERIFICARE / PARZIALE).`n`n" }
$testo += "Vuoi aprire il registro della conversione in Excel?"

Start-Process explorer.exe $Markdown
$icona = if ($codice -ne 0 -or $daControllare -gt 0) { 'Warning' } else { 'Information' }
if ((Messaggio $testo 'YesNo' $icona) -eq 'Yes' -and (Test-Path $Registro)) { Start-Process $Registro }
