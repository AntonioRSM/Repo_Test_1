# Server dei modelli locali per chi non ha LM Studio: installa Ollama, lo avvia e scarica un
# modello di embedding e un LLM con tool calling. Incluso da installa.ps1 (che definisce Passo,
# Avviso, Installa-Winget e Aggiorna-Path); si può anche lanciare da solo:
#   powershell -ExecutionPolicy Bypass -File installer\ollama.ps1 [-Forza]

param(
    [switch]$Forza,                       # installa Ollama anche se LM Studio è presente
    [string]$ModelloEmbedding = 'bge-m3', # multilingue, ~1,2 GB
    [string]$ModelloLlm = 'qwen3:4b-instruct' # tool calling senza ragionamento: rapido anche su CPU, ~2,5 GB
)

$OllamaApi = 'http://127.0.0.1:11434'

if (-not (Get-Command Passo -ErrorAction SilentlyContinue)) {
    function Passo($t)  { Write-Host "`n==> $t" -ForegroundColor Cyan }
    function Avviso($t) { Write-Host "[!] $t" -ForegroundColor Yellow }
    function Aggiorna-Path {
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('Path', 'User')
    }
    function Installa-Winget($id, $nome) {
        Write-Host "Installo $nome con winget..."
        winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements | Out-Host
        Aggiorna-Path
    }
}

function Trova-LmStudio {
    $percorsi = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\LM Studio\LM Studio.exe'),
        (Join-Path $env:ProgramFiles 'LM Studio\LM Studio.exe'),
        (Join-Path $HOME '.lmstudio\bin\lms.exe')
    )
    return [bool]($percorsi | Where-Object { Test-Path $_ } | Select-Object -First 1)
}

function Trova-Ollama {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $exe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $exe) { return $exe }
    return $null
}

function Ollama-Risponde {
    try { Invoke-RestMethod "$OllamaApi/api/version" -TimeoutSec 3 | Out-Null; return $true } catch { return $false }
}

function Avvia-Ollama($exe) {
    if (Ollama-Risponde) { return $true }
    # L'app della tray avvia il server e si riavvia con Windows; ollama serve è il ripiego.
    $app = Join-Path (Split-Path $exe) 'ollama app.exe'
    if (Test-Path $app) { Start-Process -FilePath $app }
    else { Start-Process -FilePath $exe -ArgumentList 'serve' -WindowStyle Hidden }
    for ($i = 0; $i -lt 60; $i++) {
        if (Ollama-Risponde) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Nome-Completo($m) { if ($m -match ':') { $m } else { "${m}:latest" } }

function Modelli-Installati {
    try { return @((Invoke-RestMethod "$OllamaApi/api/tags" -TimeoutSec 10).models | ForEach-Object { Nome-Completo $_.name }) }
    catch { return @() }
}

# Restituisce un hashtable con l'esito: Pronto, Embedding, Llm (nomi completi dei modelli scaricati).
function Prepara-Ollama {
    $esito = @{ Pronto = $false; Embedding = $null; Llm = $null }

    if ((Trova-LmStudio) -and -not $Forza) {
        Write-Host 'LM Studio è installato: uso quello e salto Ollama (rilancia con -Ollama per installarlo comunque).'
        return $esito
    }

    $exe = Trova-Ollama
    if (-not $exe) {
        if ($Forza) { Write-Host 'Installo Ollama, il server dei modelli locali (richiesto con -Ollama).' }
        else { Write-Host 'LM Studio non trovato: installo Ollama, il server dei modelli locali.' }
        Installa-Winget 'Ollama.Ollama' 'Ollama'
        $exe = Trova-Ollama
    }
    if (-not $exe) {
        Avviso 'Ollama non installato. Scaricalo da https://ollama.com/download e rilancia INSTALLA.bat.'
        return $esito
    }
    Write-Host "Ollama: $exe"

    if (-not (Avvia-Ollama $exe)) {
        Avviso "Ollama non risponde su $OllamaApi. Avvialo dal menu Start e rilancia INSTALLA.bat."
        return $esito
    }

    $installati = Modelli-Installati
    foreach ($m in @($ModelloEmbedding, $ModelloLlm)) {
        $nome = Nome-Completo $m
        if ($installati -contains $nome) { Write-Host "Modello $nome già presente."; continue }
        Write-Host "Scarico $nome (la prima volta può richiedere diversi minuti)..."
        & $exe pull $m
        if ($LASTEXITCODE -ne 0) {
            Avviso "Download di $nome non riuscito. Potrai scaricarlo dalla pagina Modelli dell'app."
        }
    }

    $installati = Modelli-Installati
    if ($installati -contains (Nome-Completo $ModelloEmbedding)) { $esito.Embedding = Nome-Completo $ModelloEmbedding }
    if ($installati -contains (Nome-Completo $ModelloLlm)) { $esito.Llm = Nome-Completo $ModelloLlm }
    $esito.Pronto = $true
    return $esito
}

# Workspace Harness invia un prompt di circa 8.500 token, oltre il contesto predefinito di Ollama
# (4.096). Crea "workspace-agent": lo stesso LLM con un contesto di 16.384 token. Riusa i pesi già
# scaricati, quindi non scarica nulla; restituisce $true se il modello è disponibile.
function Crea-ModelloAgente {
    $exe = Trova-Ollama
    if (-not $exe -or -not (Ollama-Risponde)) {
        Write-Host 'Ollama non è attivo: salto il modello per Workspace Harness (con LM Studio imposta un contesto di almeno 16.384 token).'
        return $false
    }
    $base = Nome-Completo $ModelloLlm
    if (-not ((Modelli-Installati) -contains $base)) {
        Avviso "Il modello $base non è installato: Workspace Harness userà i modelli disponibili."
        return $false
    }
    $file = Join-Path $env:TEMP 'workspace-agent.Modelfile'
    Set-Content -Path $file -Encoding ASCII -Value @("FROM $base", 'PARAMETER num_ctx 16384')
    Write-Host "Creo workspace-agent ($base con contesto di 16.384 token)..."
    & $exe create workspace-agent -f $file
    $ok = $LASTEXITCODE -eq 0
    Remove-Item $file -ErrorAction SilentlyContinue
    if (-not $ok) { Avviso 'Creazione di workspace-agent non riuscita: Workspace Harness userà i modelli disponibili.' }
    return $ok
}

# Lanciato da solo (non incluso da installa.ps1): esegue subito.
if ($MyInvocation.InvocationName -ne '.') {
    $r = Prepara-Ollama
    $r | Format-Table -AutoSize | Out-Host
}
