# Installa o aggiorna RAG Vault Studio su Windows 11 e crea i collegamenti nel menu Start.
# Avvio: doppio clic su INSTALLA.bat nella cartella principale del progetto.
# Con -Aggiorna (usato dal collegamento "Aggiorna RAG Vault Studio") scarica prima l'ultima versione con git.
# Senza LM Studio installa Ollama e scarica i modelli predefiniti; -Ollama lo fa anche se LM Studio c'è,
# -SenzaModelli salta del tutto il passo dei modelli locali.
# Workspace Harness (DeepSeek Harness in italiano con il marchio Workspace) è facoltativo: l'installer
# lo chiede; -Harness lo installa senza chiedere, -SenzaHarness lo salta.
param([switch]$Aggiorna, [switch]$Ollama, [switch]$SenzaModelli, [switch]$Harness, [switch]$SenzaHarness)

$ErrorActionPreference = 'Continue'   # gli errori gravi sono gestiti esplicitamente

$Radice    = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Engine    = Join-Path $Radice 'engine'
$Desktop   = Join-Path $Radice 'desktop'
$Electron  = Join-Path $Desktop 'node_modules\electron\dist\electron.exe'
$DirHarness = Join-Path $Radice 'harness'
$MenuStart = Join-Path ([Environment]::GetFolderPath('Programs')) 'RAG Vault Studio'

# Stile Workspace: chevron e cursore "sm" in azzurro #2E6BD6 (colori a 24 bit dove la console li supporta).
$Vt = $Host.UI.SupportsVirtualTerminal
$E = [char]27
function Azzurro($t) { if ($Vt) { "$E[38;2;46;107;214m$t$E[0m" } else { $t } }
function Cursore($t) { if ($Vt) { "$E[48;2;46;107;214m$E[38;2;244;242;236m$t$E[0m" } else { "[$t]" } }
function Passo($t)  { Write-Host "`n$(Azzurro '>') $t" }
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

Write-Host ''
Write-Host "  $(Azzurro '>') workspace $(Cursore 'sm')   RAG Vault Studio - installazione"
Write-Host ''
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
Passo '1/6 Prerequisiti: uv (gestisce Python 3.12) e Node.js'
Aggiorna-Path
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Installa-Winget 'astral-sh.uv' 'uv' }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Esci 'uv non trovato dopo l''installazione. Chiudi questa finestra e rilancia INSTALLA.bat.' }
Write-Host "uv: $((& uv --version) -join ' ')"

if ((Versione-Node) -lt 22) { Installa-Winget 'OpenJS.NodeJS.LTS' 'Node.js LTS' }
if ((Versione-Node) -lt 22) { Esci 'Serve Node.js 22 o successivo. Chiudi questa finestra e rilancia INSTALLA.bat.' }
Write-Host "Node.js: $(& node --version)"

# ---------------------------------------------------------------- 2. motore Python
Passo '2/6 Motore Python (scarica Python 3.12 se manca)'
Push-Location $Engine
& uv sync --no-build
$esito = $LASTEXITCODE
Pop-Location
if ($esito -ne 0 -or -not (Test-Path (Join-Path $Engine '.venv\Scripts\python.exe'))) { Esci 'Installazione del motore non riuscita (uv sync).' }

# ---------------------------------------------------------------- 3. interfaccia desktop
Passo '3/6 Interfaccia desktop (Electron + React)'
Push-Location $Desktop
& npm.cmd install --no-audit --no-fund
$esito = $LASTEXITCODE
if ($esito -eq 0) { & npm.cmd run build; $esito = $LASTEXITCODE }
Pop-Location
if ($esito -ne 0) { Esci 'Installazione o compilazione dell''interfaccia non riuscita (npm).' }
if (-not (Test-Path $Electron)) { Esci "Electron non trovato in $Electron." }

# ---------------------------------------------------------------- 4. modelli locali
Passo '4/6 Modelli locali (LM Studio oppure Ollama)'
$ModelliOllama = $null
if ($SenzaModelli) {
    Write-Host 'Saltato (-SenzaModelli).'
} else {
    . (Join-Path $PSScriptRoot 'ollama.ps1') -Forza:$Ollama
    $ModelliOllama = Prepara-Ollama
    if ($ModelliOllama.Pronto) {
        # Imposta i modelli predefiniti solo dove l'utente non ha già scelto in Impostazioni.
        $argomenti = @('--provider', 'ollama')
        if ($ModelliOllama.Embedding) { $argomenti += @('--embedding', $ModelliOllama.Embedding) }
        if ($ModelliOllama.Llm) { $argomenti += @('--llm', $ModelliOllama.Llm) }
        & (Join-Path $Engine '.venv\Scripts\python.exe') -X utf8 (Join-Path $Engine 'scripts\configure_models.py') @argomenti
        if ($LASTEXITCODE -ne 0) { Avviso 'Modelli predefiniti non impostati: sceglili in Impostazioni → Model Router.' }
    }
}

# ---------------------------------------------------------------- 5. Workspace Harness
Passo '5/6 Workspace Harness (agente basato su DeepSeek Harness, facoltativo)'
$Dsh = Join-Path $DirHarness 'node_modules\@deepseek-ai\dsh\lib\bin.js'
$ConHarness = $false
if ($SenzaHarness) {
    Write-Host 'Saltato (-SenzaHarness).'
} elseif ($Harness -or (Test-Path $Dsh)) {
    $ConHarness = $true          # richiesto, oppure già installato: lo aggiorna
} else {
    Write-Host 'Workspace Harness è un agente locale in italiano (DeepSeek Harness, licenza MIT) che lavora su file,'
    Write-Host 'terminale e web con i modelli di Ollama o LM Studio. Occupa circa 830 MB.'
    $ConHarness = (Read-Host 'Installare Workspace Harness? (S/N)') -match '^[sS]'
}
if ($ConHarness) {
    Push-Location $DirHarness
    & npm.cmd install --omit=dev --no-audit --no-fund
    $esito = $LASTEXITCODE
    Pop-Location
    if ($esito -ne 0 -or -not (Test-Path $Dsh)) {
        Avviso 'Installazione di Workspace Harness non riuscita (npm): il resto dell''installazione prosegue.'
        $ConHarness = $false
    } elseif (-not $SenzaModelli) {
        # L'agente ha un prompt di circa 8.500 token: con Ollama serve un modello con contesto più ampio.
        if (-not (Get-Command Crea-ModelloAgente -ErrorAction SilentlyContinue)) { . (Join-Path $PSScriptRoot 'ollama.ps1') -Forza:$Ollama }
        Crea-ModelloAgente | Out-Null
    }
}

# ---------------------------------------------------------------- 6. menu Start
Passo '6/6 Collegamenti nel menu Start'
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

if ($ConHarness) {
    $Ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    Collegamento 'Workspace Harness' $Ps "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $DirHarness 'avvia.ps1')`"" `
        $DirHarness $Icona 'Agente locale in italiano basato su DeepSeek Harness'
}

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
if ($ConHarness) { Write-Host 'Agente in italiano:          Workspace Harness' }
if ($ModelliOllama -and $ModelliOllama.Pronto) {
    Write-Host "Modelli locali con Ollama: embedding $($ModelliOllama.Embedding), LLM $($ModelliOllama.Llm)."
    Write-Host 'Ollama parte con Windows; altri modelli si scaricano dalla pagina Modelli dell''app.'
} else {
    Write-Host 'Ricorda di avviare LM Studio (o Ollama) con un modello di embedding, es. bge-m3.'
}
if ((Read-Host "`nAvviare RAG Vault Studio adesso? (S/N)") -match '^[sS]') {
    Start-Process -FilePath $Electron -ArgumentList "`"$Desktop`"" -WorkingDirectory $Desktop
}
