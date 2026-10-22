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
if (-not (Test-Path (Join-Path $Harness 'node_modules\.bin\pnpm.cmd'))) {
    Avviso 'pnpm non installato: la pagina Plugin non potrà aggiungere plugin. Rilancia INSTALLA.bat per completare.'
}

# ── profilo Workspace in una DSH_HOME dedicata (non tocca un eventuale dsh personale) ──────────
New-Item -ItemType Directory -Force -Path $Profilo, $Lavoro | Out-Null
$Modello = Join-Path $Harness 'profile'
# Bug #23: package.json è anche il file in cui dsh registra i plugin installati dall'utente:
# si aggiungono i bundle Workspace mancanti, senza togliere nulla.
& node (Join-Path $Harness 'tools\prepara-profilo.mjs') (Join-Path $Modello 'package.json') (Join-Path $Profilo 'package.json')
if ($LASTEXITCODE -ne 0) { Esci 'Preparazione del profilo non riuscita (package.json).' }
foreach ($f in 'cordis.yml', 'cordis.patch.yml') {                     # livello dell'utente: mai sovrascritto
    if (-not (Test-Path (Join-Path $Profilo $f))) { Copy-Item (Join-Path $Modello $f) $Profilo }
}
# I plugin del profilo si risolvono dalla sua node_modules: collegamenti ai plugin Workspace installati.
# Logica condivisa con il test (Miglioramento #19): harness\tools\collegamenti.ps1.
. (Join-Path $Harness 'tools\collegamenti.ps1')
Installa-PluginWorkspace -Profilo $Profilo -Harness $Harness

# ── modelli locali ────────────────────────────────────────────────────────────────────────────
function Leggi($url) { try { Invoke-RestMethod $url -TimeoutSec 3 } catch { $null } }

$Rotte = [ordered]@{}
$Predefinito = $null
$Nascosti = @()        # modelli Ollama con contesto troppo piccolo per l'agente

$Ollama = Leggi 'http://127.0.0.1:11434/api/tags'
if ($Ollama) {
    # Bug #27: il contesto effettivo non dipende solo da num_ctx del Modelfile. Vale anche il
    # contesto del server (variabile OLLAMA_CONTEXT_LENGTH, es. 32.768 per tutti i modelli) e,
    # per i modelli già caricati, quello reale riportato da /api/ps. Ignorarli nascondeva
    # all'agente modelli perfettamente utilizzabili.
    $ctxServer = [Environment]::GetEnvironmentVariable('OLLAMA_CONTEXT_LENGTH', 'User')
    if (-not $ctxServer) { $ctxServer = [Environment]::GetEnvironmentVariable('OLLAMA_CONTEXT_LENGTH', 'Machine') }
    $caricati = @{}
    $ps = Leggi 'http://127.0.0.1:11434/api/ps'
    # Contesto reale per i modelli caricati: /api/ps può omettere context_length
    # ([int]$null darebbe 0 e il modello verrebbe nascosto per errore).
    if ($ps) { foreach ($m in $ps.models) { if ($m.context_length) { $caricati[$m.name] = [int]$m.context_length } } }
    $modelli = @()
    foreach ($m in $Ollama.models) {
        $info = try { Invoke-RestMethod 'http://127.0.0.1:11434/api/show' -Method Post -Body (@{ model = $m.name } | ConvertTo-Json) -TimeoutSec 5 } catch { $null }
        if ($info -and $info.capabilities -and -not ($info.capabilities -contains 'completion')) { continue }   # solo embedding
        # Precedenza: contesto reale del modello già caricato, poi num_ctx del Modelfile,
        # poi il contesto predefinito del server, infine il valore di fallback di Ollama.
        if ($caricati.ContainsKey($m.name)) { $ctx = $caricati[$m.name] }
        elseif ($info -and $info.parameters -match 'num_ctx\s+(\d+)') { $ctx = [int]$Matches[1] }
        elseif ($ctxServer -match '^\d+$') { $ctx = [int]$ctxServer }
        else { $ctx = 4096 }
        # Il prompt dell'agente occupa circa 8.500 token: un modello che Ollama carica con meno contesto
        # fallisce a ogni messaggio ("request exceeds the available context size"), quindi non si offre.
        if ($ctx -lt 12000) { $Nascosti += $m.name; continue }
        $modelli += [ordered]@{ id = $m.name; name = $m.name; contextWindow = $ctx; reasoningEfforts = $false }
        if ($m.name -like 'workspace-agent*') { $Predefinito = @('ollama-locale', $m.name) }
    }
    if ($modelli.Count) {
        $Rotte['ollama-locale'] = [ordered]@{ displayName = 'Ollama (locale)'; api = 'openai-completions'; baseURL = 'http://127.0.0.1:11434/v1'; apiKeyEnv = 'WSOS_LOCAL_LLM_KEY'; models = $modelli }
        Riga "Ollama: $($modelli.Count) modelli ($(($modelli | ForEach-Object { $_.id }) -join ', '))"
    }
    if ($Nascosti.Count) {
        $alternativa = if ($Predefinito) { "usa $($Predefinito[1])" } else { 'rilancia INSTALLA.bat per creare workspace-agent' }
        Write-Host "    $(Grigio "Non offerti all'agente (contesto sotto 12.000 token): $($Nascosti -join ', '); $alternativa")"
        # Miglioramento #22: un contesto ampio impostato dalle Impostazioni dell'app
        # Ollama NON è leggibile dall'esterno (non è una variabile d'ambiente), quindi
        # quei modelli risulterebbero nascosti per errore. Indica il rimedio.
        if (-not $ctxServer) {
            Write-Host "    $(Grigio "Se hai impostato un contesto più ampio nelle Impostazioni dell'app Ollama, imposta anche la variabile OLLAMA_CONTEXT_LENGTH oppure rilancia INSTALLA.bat per creare workspace-agent: quel valore non è leggibile dalla Harness.")"
        }
    }
}

$LmStudio = Leggi 'http://127.0.0.1:1234/api/v0/models'
if ($LmStudio) {
    # Bug #25: a model that is not loaded is loaded on demand with LM Studio's DEFAULT context
    # (often 4.096), not with max_context_length: only the loaded length can be trusted.
    $ContestoNonCaricato = 4096
    $strumenti = @{}                       # modelli addestrati per il tool calling (API v1, se presente)
    $v1 = Leggi 'http://127.0.0.1:1234/api/v1/models'
    if ($v1) { foreach ($m in $v1.models) { if ($m.capabilities.trained_for_tool_use) { $strumenti[$m.key] = $true } } }
    $modelli = @()
    foreach ($m in $LmStudio.data) {
        if ($m.type -eq 'embeddings') { continue }
        $caricato = $m.state -eq 'loaded' -and $m.loaded_context_length
        $ctx = if ($caricato) { [int]$m.loaded_context_length } else { $ContestoNonCaricato }
        $modelli += [ordered]@{ id = $m.id; name = $m.id; contextWindow = $ctx; reasoningEfforts = $false
                                caricato = [bool]$caricato; strumenti = $strumenti.ContainsKey($m.id) -or ($m.capabilities -contains 'tool_use') }
    }
    if ($modelli.Count) {
        Riga "LM Studio: $($modelli.Count) modelli"
        if (-not $Predefinito) {
            # Preferisce un modello già caricato con contesto sufficiente, poi uno con tool calling.
            $scelto = @($modelli | Where-Object { $_.caricato -and $_.contextWindow -ge 12000 -and $_.strumenti }) +
                      @($modelli | Where-Object { $_.caricato -and $_.contextWindow -ge 12000 }) +
                      @($modelli | Where-Object { $_.strumenti }) + $modelli | Select-Object -First 1
            if ($scelto.contextWindow -lt 12000) {
                Riga "Carico $($scelto.id) in LM Studio con un contesto di $ContestoAgente token (può richiedere qualche minuto)..."
                # Miglioramento #18 (corretto al ciclo 7): LM Studio 0.4.x richiede
                # instance_id per lo scarico — verificato su 0.4.25: HTTP 400 "Missing
                # required field 'instance_id'" se si passa il nome. L'id si legge da
                # /api/v1/models → loaded_instances. Se NON si riesce a scaricare
                # NON si carica: una load senza scarico crea una seconda istanza
                # (modello:2, doppia RAM/VRAM) e le richieste restano instradate sulla
                # prima, ancora a contesto piccolo.
                # Miglioramento #21: possono restare PIÙ istanze dello stesso modello
                # (per esempio una "modello:2" lasciata da un avvio precedente):
                # vanno scaricate TUTTE, non solo la prima.
                $scaricato = -not $scelto.caricato
                if ($scelto.caricato) {
                    $ids = @()
                    $elenco = Leggi 'http://127.0.0.1:1234/api/v1/models'
                    if ($elenco -and $elenco.models) {
                        $voce = @($elenco.models | Where-Object { $_.key -eq $scelto.id })[0]
                        if ($voce -and $voce.loaded_instances) { $ids = @($voce.loaded_instances | ForEach-Object { $_.id }) }
                    }
                    $tentativi = @($ids | ForEach-Object { @{ instance_id = $_ } })
                    if (-not $tentativi.Count) { $tentativi = @(@{ model = $scelto.id }) }   # versioni senza API v1: ripiego sul nome
                    $scaricato = $true
                    foreach ($corpoUnload in $tentativi) {
                        try {
                            Invoke-RestMethod 'http://127.0.0.1:1234/api/v1/models/unload' -Method Post -Body ($corpoUnload | ConvertTo-Json) -ContentType 'application/json' -TimeoutSec 120 | Out-Null
                        } catch {
                            $scaricato = $false   # basta una istanza rimasta in memoria per rovinare il ricarico
                        }
                    }
                }
                if (-not $scaricato) {
                    Avviso "Scarico di $($scelto.id) non riuscito: salto il caricamento per non creare una seconda istanza. In LM Studio scarica il modello e ricaricalo con almeno $ContestoAgente token di contesto."
                } else {
                    try {
                        $corpo = @{ model = $scelto.id; context_length = $ContestoAgente } | ConvertTo-Json
                        Invoke-RestMethod 'http://127.0.0.1:1234/api/v1/models/load' -Method Post -Body $corpo -ContentType 'application/json' -TimeoutSec 300 | Out-Null
                        $scelto.contextWindow = $ContestoAgente
                        # Miglioramento #21: dopo il load si rilegge /api/v1/models e si
                        # controlla l'esito reale: esattamente UNA istanza, con contesto
                        # di almeno $ContestoAgente token. Altrimenti si avvisa.
                        $dopo = Leggi 'http://127.0.0.1:1234/api/v1/models'
                        if ($dopo -and $dopo.models) {
                            $voceDopo = @($dopo.models | Where-Object { $_.key -eq $scelto.id })[0]
                            $nIstanze = 0
                            $ctxReale = 0
                            if ($voceDopo -and $voceDopo.loaded_instances) {
                                $nIstanze = @($voceDopo.loaded_instances).Count
                                $ctxIstanza = @($voceDopo.loaded_instances)[0].config.context_length
                                if ($ctxIstanza) { $ctxReale = [int]$ctxIstanza }
                            }
                            if ($nIstanze -ne 1 -or ($ctxReale -and $ctxReale -lt $ContestoAgente)) {
                                $comeContesto = if ($ctxReale) { "$ctxReale" } else { 'sconosciuto' }
                                Avviso "Esito inatteso dopo il caricamento di $($scelto.id): $nIstanze istanze, contesto $comeContesto (atteso: 1 istanza con almeno $ContestoAgente token). In LM Studio scarica tutte le istanze del modello e ricaricalo con almeno $ContestoAgente token di contesto."
                                if ($ctxReale) { $scelto.contextWindow = $ctxReale }
                            }
                        }
                    } catch {
                        Avviso "Caricamento non riuscito: in LM Studio carica $($scelto.id) con almeno $ContestoAgente token di contesto."
                    }
                }
            }
            $Predefinito = @('lmstudio-locale', $scelto.id)
        }
        foreach ($m in $modelli) {
            if ($m.contextWindow -lt 12000) {
                $come = if ($m.caricato) { 'caricato con' } else { 'non caricato: LM Studio userà il contesto predefinito, circa' }
                Write-Host "    $(Grigio "$($m.id): $come $($m.contextWindow) token, troppo pochi per l'agente (serve circa 12.000)")"
            }
            $m.Remove('caricato'); $m.Remove('strumenti')     # campi interni, non vanno a dsh
        }
        $Rotte['lmstudio-locale'] = [ordered]@{ displayName = 'LM Studio (locale)'; api = 'openai-completions'; baseURL = 'http://127.0.0.1:1234/v1'; apiKeyEnv = 'WSOS_LOCAL_LLM_KEY'; models = $modelli }
    }
}

if (-not $Rotte.Count) { Avviso 'Nessun modello locale trovato (Ollama o LM Studio). Potrai configurare un provider dalla pagina Modelli.' }
if (-not $Predefinito -and $Rotte.Contains('ollama-locale')) { $Predefinito = @('ollama-locale', $Rotte['ollama-locale'].models[0].id) }
if ($Predefinito) { Riga "Modello predefinito: $($Predefinito[1])" }

# Bug #27: se il modello salvato dalle Impostazioni non è più offerto (contesto troppo piccolo),
# NON si riscrive più il suo file in silenzio: si avvisa e la scelta resta all'utente.
$PatchUtente = Join-Path $Profilo 'cordis.patch.yml'
if ($Nascosti.Count -and $Predefinito -and $Predefinito[0] -eq 'ollama-locale' -and (Test-Path $PatchUtente)) {
    $testo = [IO.File]::ReadAllText($PatchUtente)
    $nomi = ($Nascosti | ForEach-Object { [regex]::Escape($_) }) -join '|'
    if ([regex]::IsMatch($testo, "(?m)^\s*provider:\s*[`"']?ollama-locale[`"']?\s*\r?\n\s*model:\s*[`"']?(?:$nomi)[`"']?[ \t]*(?=\r?$)")) {
        Avviso "Il modello scelto nelle Impostazioni ha un contesto troppo piccolo per l'agente: aprilo e cambialo (suggerito: $($Predefinito[1]))."
    }
}

$env:DSH_HOME = $DshHome
# Bug #24: il gestore dei plugin di dsh esegue "pnpm"; quello fissato in harness/package.json
# viene prima di un eventuale pnpm di sistema.
$env:Path = (Join-Path $Harness 'node_modules\.bin') + ';' + $env:Path
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
# Bug #22: in Windows PowerShell 5.1 ogni riga stderr di un programma nativo diventa un
# ErrorRecord, che con 'Stop' chiuderebbe la finestra al primo avviso di dsh o di Node.
$ErrorActionPreference = 'Continue'
& node $Dsh --profile workspace --port $Porta --no-open 2>&1 | ForEach-Object {
    $riga = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" }
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
$codice = $LASTEXITCODE
Write-Host ''
if ($codice -ne 0) { Esci "Workspace Harness si è fermato con un errore (codice $codice): leggi i messaggi qui sopra." }
Riga 'Workspace Harness si è fermato.'
