# Installa o aggiorna RAG Vault Studio su Windows 11 e crea i collegamenti nel menu Start.
# Avvio: doppio clic su INSTALLA.bat nella cartella principale del progetto.
# Con -Aggiorna (usato dal collegamento "Aggiorna RAG Vault Studio") scarica prima l'ultima versione con git.
param([switch]$Aggiorna)

$ErrorActionPreference = 'Continue'   # gli errori gravi sono gestiti esplicitamente

$Radice    = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Engine    = Join-Path $Radice 'engine'
$Desktop   = Join-Path $Radice 'desktop'
$Electron  = Join-Path $Desktop 'node_modules\electron\dist\electron.exe'
$MenuStart = Join-Path ([Environment]::GetFolderPath('Programs')) 'RAG Vault Studio'

function Passo($t)  { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Avviso($t) { Write-Host "[!] $t" -ForegroundColor Yellow }
function Esci($t)   { Write-Host "`n[X] $t" -ForegroundColor Red; Read-Host 'Premi Invio per chiudere'; exit 1 }

# winget aggiorna il PATH di sistema, ma non quello di questa finestra: lo rilegge dal registro
function Aggiorna-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Installa-Winget($id, $nome) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Esci "winget non disponibile. Aggiorna 'Programma di installazione app' dal Microsoft Store e riprova."
    }
    Write-Host "Installo $nome con winget (potrebbe comparire la richiesta di autorizzazione di Windows)..."
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements | Out-Host
    Aggiorna-Path
}

function Versione-Node {
    try { return [int]((& node --version) -replace '^v(\d+).*', '$1') } catch { return 0 }
}

if (-not (Test-Path (Join-Path $Engine 'pyproject.toml')) -or -not (Test-Path (Join-Path $Desktop 'package.json'))) {
    Esci "Cartelle 'engine' e 'desktop' non trovate accanto a INSTALLA.bat ($Radice)."
}

Write-Host '==========================================' -ForegroundColor Green
Write-Host '  RAG Vault Studio - installazione' -ForegroundColor Green
Write-Host '==========================================' -ForegroundColor Green
Write-Host "Cartella: $Radice"

# con l'app aperta Windows blocca electron.exe e i file del motore: l'installazione fallirebbe a metà
$Aperta = Get-Process -Name electron -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Electron }
if ($Aperta) { Esci 'RAG Vault Studio è aperto: chiudilo (anche dall''icona vicino all''orologio) e rilancia.' }

# ---------------------------------------------------------------- 0. aggiornamento del codice
if ($Aggiorna) {
    Passo 'Scarico l''ultima versione'
    if ((Test-Path (Join-Path $Radice '.git')) -and (Get-Command git -ErrorAction SilentlyContinue)) {
        & git -C $Radice pull --ff-only
        if ($LASTEXITCODE -ne 0) { Esci 'git pull non riuscito: ci sono modifiche locali o una connessione assente.' }
    } else {
        Avviso 'Questa cartella non è un clone git: scarica la nuova versione a mano e rilancia INSTALLA.bat.'
    }
}

# ---------------------------------------------------------------- 1. prerequisiti
Passo '1/4 Prerequisiti: uv (gestisce Python 3.12) e Node.js'
Aggiorna-Path
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Installa-Winget 'astral-sh.uv' 'uv' }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Esci 'uv non trovato dopo l''installazione. Chiudi questa finestra e rilancia INSTALLA.bat.' }
Write-Host "uv: $((& uv --version) -join ' ')"

if ((Versione-Node) -lt 22) { Installa-Winget 'OpenJS.NodeJS.LTS' 'Node.js LTS' }
if ((Versione-Node) -lt 22) { Esci 'Serve Node.js 22 o successivo. Chiudi questa finestra e rilancia INSTALLA.bat.' }
Write-Host "Node.js: $(& node --version)"

# ---------------------------------------------------------------- 2. motore Python
Passo '2/4 Motore Python (scarica Python 3.12 se manca)'
Push-Location $Engine
& uv sync --no-build
$esito = $LASTEXITCODE
Pop-Location
if ($esito -ne 0 -or -not (Test-Path (Join-Path $Engine '.venv\Scripts\python.exe'))) { Esci 'Installazione del motore non riuscita (uv sync).' }

# ---------------------------------------------------------------- 3. interfaccia desktop
Passo '3/4 Interfaccia desktop (Electron + React)'
Push-Location $Desktop
& npm.cmd install --no-audit --no-fund
$esito = $LASTEXITCODE
if ($esito -eq 0) { & npm.cmd run build; $esito = $LASTEXITCODE }
Pop-Location
if ($esito -ne 0) { Esci 'Installazione o compilazione dell''interfaccia non riuscita (npm).' }
if (-not (Test-Path $Electron)) { Esci "Electron non trovato in $Electron." }

# ---------------------------------------------------------------- 4. menu Start
Passo '4/4 Collegamenti nel menu Start'
New-Item -ItemType Directory -Force -Path $MenuStart | Out-Null
$Shell = New-Object -ComObject WScript.Shell
function Collegamento($nome, $target, $argomenti, $cartella, $icona, $descr) {
    $l = $Shell.CreateShortcut((Join-Path $MenuStart "$nome.lnk"))
    $l.TargetPath = $target
    $l.Arguments = $argomenti
    $l.WorkingDirectory = $cartella
    $l.IconLocation = $icona
    $l.Description = $descr
    $l.Save()
}
$Icona = Join-Path $Desktop 'assets\icon.ico'
Collegamento 'RAG Vault Studio' $Electron "`"$Desktop`"" $Desktop $Icona 'Archivi RAG locali e agente'

$Manuale = Join-Path $Radice 'docs\Manuale-RAG-Vault-Studio.html'
if (Test-Path $Manuale) {
    Collegamento 'Manuale RAG Vault Studio' $Manuale '' (Split-Path $Manuale) "$env:SystemRoot\System32\imageres.dll,97" 'Manuale d''uso'
}
if (Test-Path (Join-Path $Radice '.git')) {
    $Ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    Collegamento 'Aggiorna RAG Vault Studio' $Ps "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Aggiorna" `
        $Radice "$env:SystemRoot\System32\imageres.dll,229" 'Scarica l''ultima versione e la reinstalla'
}

Write-Host "`nInstallazione completata." -ForegroundColor Green
Write-Host 'Apri il menu Start e cerca:  RAG Vault Studio'
Write-Host 'Ricorda di avviare LM Studio (o Ollama) con un modello di embedding, es. bge-m3.'
if ((Read-Host "`nAvviare RAG Vault Studio adesso? (S/N)") -match '^[sS]') {
    Start-Process -FilePath $Electron -ArgumentList "`"$Desktop`"" -WorkingDirectory $Desktop
}
