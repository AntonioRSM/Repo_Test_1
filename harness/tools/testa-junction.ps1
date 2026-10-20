# Test mirato della gestione sicura dei junction (Bug #26) e del collegamento dei
# plugin (Miglioramento #19): usa la STESSA funzione di avvia.ps1
# (tools\collegamenti.ps1), in cartelle temporanee; ripulisce tutto alla fine.
$ErrorActionPreference = 'Stop'
$falliti = 0
function Verifica($nome, $cond) {
    if ($cond) { Write-Host "ok   $nome" } else { Write-Host "FAIL $nome"; $script:falliti++ }
}

. (Join-Path $PSScriptRoot 'collegamenti.ps1')

$root = Join-Path $env:TEMP 'wsos-bug26-test'
Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
$plugin = 'dsh-workspace-brand'
New-Item -ItemType Directory -Force "$root\A\harness\plugins\$plugin", "$root\B\harness\plugins\$plugin", "$root\profilo\node_modules\@workspace-sm" | Out-Null
Set-Content "$root\A\harness\plugins\$plugin\fileA.txt" 'contenuto A'
Set-Content "$root\B\harness\plugins\$plugin\fileB.txt" 'contenuto B'

$link = "$root\profilo\node_modules\@workspace-sm\$plugin"
# la funzione collega entrambi i plugin: il secondo serve solo a completare il profilo
New-Item -ItemType Directory -Force "$root\A\harness\plugins\dsh-workspace-it", "$root\B\harness\plugins\dsh-workspace-it" | Out-Null

# Caso 1: collegamento valido → riconosciuto e lasciato stare (skip).
New-Item -ItemType Junction -Path $link -Target "$root\A\harness\plugins\$plugin" | Out-Null
Installa-PluginWorkspace -Profilo "$root\profilo" -Harness "$root\A\harness"
Verifica 'junction valido riconosciuto (skip)' ((Get-Item -LiteralPath $link -Force).Target -contains "$root\A\harness\plugins\$plugin")

# Caso 2 (scenario del Bug #26, come da passi originali): il collegamento diventa
# ORFANO (A rinominata e ASSENTE al suo posto) e poi viene chiamata la funzione verso B:
# deve sostituire il collegamento orfano SENZA toccare A-spostata e SENZA errori.
Rename-Item "$root\A" "$root\A-spostata"
Installa-PluginWorkspace -Profilo "$root\profilo" -Harness "$root\B\harness"
Verifica 'junction orfano sostituito verso B mentre A assente' ((Get-Content "$link\fileB.txt") -eq 'contenuto B')
Verifica 'A-spostata intatta durante la sostituzione' ((Get-Content "$root\A-spostata\harness\plugins\$plugin\fileA.txt") -eq 'contenuto A')

# Caso 3: A torna al suo nome; collegamento verso un'altra copia esistente → riattacco ad A.
Rename-Item "$root\A-spostata" "$root\A"
Installa-PluginWorkspace -Profilo "$root\profilo" -Harness "$root\A\harness"
Verifica 'collegamento verso altra copia riattaccato ad A' ((Get-Content "$link\fileA.txt") -eq 'contenuto A')
Verifica 'contenuto della copia B intatto' ((Get-Content "$root\B\harness\plugins\$plugin\fileB.txt") -eq 'contenuto B')

Remove-Item -Recurse -Force "$root\A", "$root\B", "$root\profilo"
if ($falliti) { Write-Host "$falliti verifiche fallite"; exit 1 }
Write-Host 'Tutte le verifiche superate'
