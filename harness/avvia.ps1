# Avvia Workspace Harness: DeepSeek Harness (MIT) con il profilo Workspace OS, in italiano,
# con il marchio Workspace e i modelli locali (Ollama / LM Studio) già collegati.
# Uso: collegamento "Workspace Harness" nel menu Start, oppure
#   powershell -ExecutionPolicy Bypass -File harness\avvia.ps1 [-Porta 18790] [-NonAprire] [-Cartella <percorso>]
param(
    [int]$Porta = 0,          # 0 = prima porta libera
    [switch]$NonAprire,       # non aprire il browser
    [string]$Cartella = ''    # cartella di lavoro; predefinita Documenti\Workspace Harness
)

$ErrorActionPreference = 'Stop'
$Harness  = $PSScriptRoot
$Dsh      = Join-Path $Harness 'node_modules\@deepseek-ai\dsh\lib\bin.js'
$DataDir  = if ($env:WSOS_DATA_DIR) { $env:WSOS_DATA_DIR } else { Join-Path $env:LOCALAPPDATA 'WorkspaceOS' }
$DshHome  = Join-Path $DataDir 'harness'
$Profilo  = Join-Path $DshHome 'profiles\workspace'
$Lavoro   = if ($Cartella) { $Cartella } else { Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Workspace Harness' }
$ContestoAgente = 16384

# ── stile Workspace: chevron e cursore azzurri (#2E6BD6), testo inchiostro/carta ──────────────
$Vt = $Host.UI.SupportsVirtualTerminal
$E = [char]27
function Azzurro($t) { if ($Vt) { "$E[38;2;46;107;214m$t$E[0m" } else { $t } }
function Cursore($t) { if ($Vt) { "$E[48;2;46;107;214m$E[38;2;244;242;236m$t$E[0m" } else { "[$t]" } }
function Grigio($t)  { if ($Vt) { "$E[38;2;164;167;175m$t$E[0m" } else { $t } }
function Riga($t)    { Write-Host "$(Azzurro '>') $t" }
function Avviso($t)  { Write-Host "$(Azzurro '!') $t" -ForegroundColor Yellow }
function Esci($t)    { Write-Host "`n$(Azzurro 'x') $t" -ForegroundColor Red; Read-Host 'Premi Invio per chiudere'; exit 1 }

Write-Host ''
Write-Host "  $(Azzurro '>') workspace $(Cursore 'sm')   Harness"
Write-Host "  $(Grigio 'Agente locale basato su DeepSeek Harness (licenza MIT)')"
Write-Host ''

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Esci 'Node.js non trovato. Rilancia INSTALLA.bat.' }
if (-not (Test-Path $Dsh)) { Esci 'DeepSeek Harness non è installato. Rilancia INSTALLA.bat e rispondi S alla domanda su Workspace Harness.' }

# ── profilo Workspace in una DSH_HOME dedicata (non tocca un eventuale dsh personale) ──────────
New-Item -ItemType Directory -Force -Path $Profilo, $Lavoro | Out-Null
$Modello = Join-Path $Harness 'profile'
Copy-Item (Join-Path $Modello 'package.json') $Profilo -Force          # bundle del profilo: sempre aggiornati
foreach ($f in 'cordis.yml', 'cordis.patch.yml') {                     # livello dell'utente: mai sovrascritto
    if (-not (Test-Path (Join-Path $Profilo $f))) { Copy-Item (Join-Path $Modello $f) $Profilo }
}
# I plugin del profilo si risolvono dalla sua node_modules: collegamenti ai plugin Workspace installati.
$Scope = Join-Path $Profilo 'node_modules\@workspace-sm'
New-Item -ItemType Directory -Force -Path $Scope | Out-Null
foreach ($p in 'dsh-workspace-brand', 'dsh-workspace-it') {
    $link = Join-Path $Scope $p
    $target = Join-Path $Harness "plugins\$p"
    if (Test-Path $link) {
        $item = Get-Item $link -Force
        if ($item.LinkType -eq 'Junction' -and $item.Target -contains $target) { continue }
        Remove-Item $link -Recurse -Force
    }
    New-Item -ItemType Junction -Path $link -Target $target | Out-Null
}

# ── modelli locali ────────────────────────────────────────────────────────────────────────────
function Leggi($url) { try { Invoke-RestMethod $url -TimeoutSec 3 } catch { $null } }

$Rotte = [ordered]@{}
$Predefinito = $null

$Ollama = Leggi 'http://127.0.0.1:11434/api/tags'
if ($Ollama) {
    $modelli = @()
    foreach ($m in $Ollama.models) {
        $info = try { Invoke-RestMethod 'http://127.0.0.1:11434/api/show' -Method Post -Body (@{ model = $m.name } | ConvertTo-Json) -TimeoutSec 5 } catch { $null }
        if ($info -and $info.capabilities -and -not ($info.capabilities -contains 'completion')) { continue }   # solo embedding
        $ctx = 4096
        if ($info.parameters -match 'num_ctx\s+(\d+)') { $ctx = [int]$Matches[1] }
        $modelli += [ordered]@{ id = $m.name; name = $m.name; contextWindow = $ctx; reasoningEfforts = $false }
        if ($m.name -like 'workspace-agent*') { $Predefinito = @('ollama-locale', $m.name) }
    }
    if ($modelli.Count) {
        $Rotte['ollama-locale'] = [ordered]@{ displayName = 'Ollama (locale)'; api = 'openai-completions'; baseURL = 'http://127.0.0.1:11434/v1'; apiKeyEnv = 'WSOS_LOCAL_LLM_KEY'; models = $modelli }
        Riga "Ollama: $($modelli.Count) modelli ($(($modelli | ForEach-Object { $_.id }) -join ', '))"
        foreach ($m in $modelli) {
            if ($m.contextWindow -lt 12000) { Write-Host "    $(Grigio "$($m.id): contesto di $($m.contextWindow) token, troppo piccolo per l'agente (serve circa 12.000)")" }
        }
    }
}

$LmStudio = Leggi 'http://127.0.0.1:1234/api/v0/models'
if ($LmStudio) {
    $modelli = @()
    foreach ($m in $LmStudio.data) {
        if ($m.type -eq 'embeddings') { continue }
        $ctx = if ($m.loaded_context_length) { [int]$m.loaded_context_length } elseif ($m.max_context_length) { [int]$m.max_context_length } else { 8192 }
        $modelli += [ordered]@{ id = $m.id; name = $m.id; contextWindow = $ctx; reasoningEfforts = $false }
    }
    if ($modelli.Count) {
        $Rotte['lmstudio-locale'] = [ordered]@{ displayName = 'LM Studio (locale)'; api = 'openai-completions'; baseURL = 'http://127.0.0.1:1234/v1'; apiKeyEnv = 'WSOS_LOCAL_LLM_KEY'; models = $modelli }
        Riga "LM Studio: $($modelli.Count) modelli"
        if (-not $Predefinito) { $Predefinito = @('lmstudio-locale', $modelli[0].id) }
    }
}

if (-not $Rotte.Count) { Avviso 'Nessun modello locale trovato (Ollama o LM Studio). Potrai configurare un provider dalla pagina Modelli.' }
if (-not $Predefinito -and $Rotte.Contains('ollama-locale')) { $Predefinito = @('ollama-locale', $Rotte['ollama-locale'].models[0].id) }
if ($Predefinito) { Riga "Modello predefinito: $($Predefinito[1])" }

$env:DSH_HOME = $DshHome
$env:WSOS_LOCAL_LLM_KEY = 'locale'        # Ollama e LM Studio ignorano la chiave, ma la rotta ne richiede una
$env:WSOS_DSH_PROVIDERS = ($Rotte | ConvertTo-Json -Depth 6 -Compress)
if ($Predefinito) { $env:WSOS_DSH_PROVIDER = $Predefinito[0]; $env:WSOS_DSH_MODEL = $Predefinito[1] }

# ── avvio ─────────────────────────────────────────────────────────────────────────────────────
if ($Porta -eq 0) {
    $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $l.Start(); $Porta = $l.LocalEndpoint.Port; $l.Stop()
}
Riga "Cartella di lavoro: $Lavoro"
Riga "Avvio sulla porta $Porta (chiudi questa finestra o premi Ctrl+C per fermare)"
Write-Host ''

Set-Location $Lavoro
$aperto = $false
& node $Dsh --profile workspace --port $Porta --no-open 2>&1 | ForEach-Object {
    $riga = "$_"
    if ($riga -match '^dsh web: (http\S+)') {
        Riga "Workspace Harness è pronto: $($Matches[1])"
        if (-not $NonAprire -and -not $aperto) { Start-Process $Matches[1]; $aperto = $true }
    } elseif ($riga -match '^dsh: warning: (\d+) entr') {
        Avviso "$($Matches[1]) componenti non si sono attivati:"
    } elseif ($riga -match 'EADDRINUSE') {
        Avviso "La porta $Porta è già in uso: rilancia senza -Porta per usarne una libera."
    } elseif ($riga -notmatch 'opening the default browser') {
        Write-Host "    $(Grigio $riga)"
    }
}
Write-Host ''
Riga 'Workspace Harness si è fermato.'
