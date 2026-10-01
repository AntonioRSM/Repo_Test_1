# Installa "Docling Archivio" su Windows 11 e crea il collegamento nel menu Start.
# Avvio consigliato: doppio clic su INSTALLA.bat (nella stessa cartella).
$ErrorActionPreference = 'Continue'   # gli errori gravi sono gestiti esplicitamente
$ProgressPreference = 'SilentlyContinue'   # rende Invoke-WebRequest molto più veloce

$Qui       = Split-Path -Parent $MyInvocation.MyCommand.Path
$Sorgenti  = Split-Path -Parent $Qui                       # cartella docling\
$Base      = Join-Path $env:LOCALAPPDATA 'DoclingArchivio'
$EnvDir    = Join-Path $Base 'env'
$AppDir    = Join-Path $Base 'app'
$TessData  = Join-Path $Base 'tessdata'
$Config    = Join-Path $Base 'config.json'
$MenuStart = Join-Path ([Environment]::GetFolderPath('Programs')) 'Docling Archivio'

function Passo($t)  { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Avviso($t) { Write-Host "[!] $t" -ForegroundColor Yellow }
function Esci($t)   { Write-Host "`n[X] $t" -ForegroundColor Red; Read-Host 'Premi Invio per chiudere'; exit 1 }

function Installa-Winget($id, $nome) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Esci "winget non disponibile. Aggiorna 'Programma di installazione app' dal Microsoft Store e riprova."
    }
    Write-Host "Installo $nome con winget (potrebbe comparire la richiesta di autorizzazione di Windows)..."
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements | Out-Host
}

function Trova-Python {
    $candidati = @()
    foreach ($v in '3.12', '3.13', '3.11') {
        try {
            $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { $candidati += $p.Trim() }
        } catch {}
    }
    $candidati += @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:ProgramFiles\Python313\python.exe"
    )
    foreach ($c in $candidati) { if ($c -and (Test-Path $c)) { return $c } }
    return $null
}

function Trova-Exe($nomi) {
    foreach ($n in $nomi) { if (Test-Path $n) { return $n } }
    return $null
}

Write-Host '==============================================' -ForegroundColor Green
Write-Host '  Installazione Docling Archivio (Windows 11)' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host "Cartella di installazione: $Base"

# ---------------------------------------------------------------- 1. Python
Passo '1/7 Python'
$Python = Trova-Python
if (-not $Python) {
    Installa-Winget 'Python.Python.3.12' 'Python 3.12'
    $Python = Trova-Python
    if (-not $Python) { Esci 'Python non trovato dopo l''installazione. Chiudi questa finestra e rilancia INSTALLA.bat.' }
}
Write-Host "Python: $Python"

# ---------------------------------------------------------------- 2. Tesseract OCR
Passo '2/7 Tesseract OCR (motore alternativo, italiano + inglese)'
$TessPercorsi = @("$env:ProgramFiles\Tesseract-OCR\tesseract.exe", "$env:LOCALAPPDATA\Programs\Tesseract-OCR\tesseract.exe")
$Tesseract = Trova-Exe $TessPercorsi
if (-not $Tesseract) {
    Installa-Winget 'UB-Mannheim.TesseractOCR' 'Tesseract OCR'
    $Tesseract = Trova-Exe $TessPercorsi
}
if (-not $Tesseract) { Avviso 'Tesseract non trovato: resta disponibile l''OCR predefinito (RapidOCR).' }
else { Write-Host "Tesseract: $Tesseract" }

New-Item -ItemType Directory -Force -Path $TessData | Out-Null
foreach ($lingua in 'ita', 'eng', 'osd') {
    $dest = Join-Path $TessData "$lingua.traineddata"
    if (-not (Test-Path $dest)) {
        Write-Host "Scarico il dizionario OCR '$lingua'..."
        try {
            Invoke-WebRequest "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/$lingua.traineddata" -OutFile $dest -UseBasicParsing -ErrorAction Stop
        } catch { Avviso "Download di $lingua.traineddata non riuscito: $($_.Exception.Message)" }
    }
}

# ---------------------------------------------------------------- 3. LibreOffice
Passo '3/7 LibreOffice (per i vecchi .doc, .xls, .ppt)'
$SoffPercorsi = @("$env:ProgramFiles\LibreOffice\program\soffice.exe", "${env:ProgramFiles(x86)}\LibreOffice\program\soffice.exe")
$Soffice = Trova-Exe $SoffPercorsi
if (-not $Soffice) {
    Installa-Winget 'TheDocumentFoundation.LibreOffice' 'LibreOffice'
    $Soffice = Trova-Exe $SoffPercorsi
}
if (-not $Soffice) { Avviso 'LibreOffice non trovato: i file .doc/.xls/.ppt finiranno in quarantena.' }
else { Write-Host "LibreOffice: $Soffice" }

# ---------------------------------------------------------------- 4. Ambiente Python
Passo "4/7 Ambiente Python in $EnvDir"
if (-not (Test-Path "$EnvDir\Scripts\python.exe")) { & $Python -m venv $EnvDir }
if (-not (Test-Path "$EnvDir\Scripts\python.exe")) { Esci 'Creazione dell''ambiente Python non riuscita.' }
$Py  = "$EnvDir\Scripts\python.exe"
& $Py -m pip install -q --upgrade pip wheel
if ($LASTEXITCODE -ne 0) { Esci 'Aggiornamento di pip non riuscito (controlla la connessione).' }

# ---------------------------------------------------------------- 5. PyTorch + Docling
Passo '5/7 PyTorch e Docling (alcuni GB, può richiedere vari minuti)'
$GpuNvidia = $false
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    try { & nvidia-smi *> $null; $GpuNvidia = ($LASTEXITCODE -eq 0) } catch {}
}
if ($GpuNvidia) {
    Write-Host 'GPU NVIDIA rilevata: installo PyTorch con CUDA.'
    & $Py -m pip install -q torch torchvision --index-url https://download.pytorch.org/whl/cu128
    if ($LASTEXITCODE -ne 0) { Avviso 'PyTorch CUDA non installato, uso la versione per CPU.'; & $Py -m pip install -q torch torchvision }
} else {
    Write-Host 'Nessuna GPU NVIDIA: installo PyTorch per CPU.'
    & $Py -m pip install -q torch torchvision
}
& $Py -m pip install -q "docling[rapidocr]"
if ($LASTEXITCODE -ne 0) { Esci 'Installazione di Docling non riuscita.' }

# ---------------------------------------------------------------- 6. Modelli
Passo '6/7 Modelli Docling (impaginazione, tabelle, OCR)'
& "$EnvDir\Scripts\docling-tools.exe" models download
if ($LASTEXITCODE -ne 0) { Avviso 'Download dei modelli non riuscito: verranno scaricati al primo utilizzo.' }

# ---------------------------------------------------------------- 7. App e menu Start
Passo '7/7 Programma e collegamenti nel menu Start'
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
Copy-Item (Join-Path $Sorgenti 'converti.py') $AppDir -Force
Copy-Item (Join-Path $Qui 'avvia.ps1') $AppDir -Force
Copy-Item (Join-Path $Qui 'disinstalla.ps1') $AppDir -Force
Copy-Item (Join-Path $Sorgenti 'README.md') (Join-Path $Base 'Leggimi.txt') -Force

@{
    python    = $Py
    tesseract = $Tesseract
    tessdata  = $TessData
    soffice   = $Soffice
} | ConvertTo-Json | Set-Content -Path $Config -Encoding UTF8

New-Item -ItemType Directory -Force -Path $MenuStart | Out-Null
$Shell = New-Object -ComObject WScript.Shell
function Collegamento($nome, $target, $argomenti, $icona, $descr) {
    $l = $Shell.CreateShortcut((Join-Path $MenuStart "$nome.lnk"))
    $l.TargetPath = $target
    $l.Arguments = $argomenti
    $l.WorkingDirectory = $Base
    $l.IconLocation = $icona
    $l.Description = $descr
    $l.Save()
}
$Ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
Collegamento 'Converti archivio documentale' $Ps "-NoProfile -ExecutionPolicy Bypass -File `"$AppDir\avvia.ps1`"" `
    "$env:SystemRoot\System32\imageres.dll,111" 'Converte i documenti di un progetto in Markdown per LightRAG'
Collegamento 'Leggimi' "$env:SystemRoot\notepad.exe" "`"$Base\Leggimi.txt`"" `
    "$env:SystemRoot\System32\imageres.dll,97" 'Istruzioni di Docling Archivio'
Collegamento 'Disinstalla Docling Archivio' $Ps "-NoProfile -ExecutionPolicy Bypass -File `"$AppDir\disinstalla.ps1`"" `
    "$env:SystemRoot\System32\imageres.dll,84" 'Rimuove Docling Archivio'

# Percorsi lunghi (archivi con molte sottocartelle): possibile solo da amministratore
try {
    Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -Value 1 -ErrorAction Stop
    Write-Host 'Percorsi lunghi di Windows abilitati.'
} catch { Avviso 'Percorsi lunghi non abilitati (serve l''amministratore): evita percorsi oltre 260 caratteri.' }

# ---------------------------------------------------------------- Verifica
Passo 'Verifica'
& $Py -c "import importlib.metadata as m, torch; print('Docling', m.version('docling'), '| PyTorch', torch.__version__, '| GPU CUDA:', torch.cuda.is_available())"
if ($GpuNvidia) {
    $cuda = & $Py -c "import torch; print(torch.cuda.is_available())"
    if ("$cuda".Trim() -ne 'True') { Avviso 'La GPU NVIDIA non viene usata da PyTorch: la conversione funzionerà ma più lentamente (solo CPU).' }
}
if ($Tesseract) {
    $env:TESSDATA_PREFIX = $TessData
    $lingue = & $Tesseract --list-langs 2>$null
    if ($lingue -contains 'ita') { Write-Host 'Tesseract: italiano OK' } else { Avviso 'Dizionario italiano di Tesseract mancante.' }
}

Write-Host "`nInstallazione completata." -ForegroundColor Green
Write-Host "Apri il menu Start e cerca:  Converti archivio documentale"
Read-Host "`nPremi Invio per chiudere"
