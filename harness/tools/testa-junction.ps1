# Test mirato della gestione sicura dei junction (Bug #26): replica la sequenza di
# avvia.ps1 in cartelle temporanee e ripulisce tutto alla fine.
$ErrorActionPreference = 'Stop'
$falliti = 0
function Verifica($nome, $cond) {
    if ($cond) { Write-Host "ok   $nome" } else { Write-Host "FAIL $nome"; $script:falliti++ }
}

$root = Join-Path $env:TEMP 'wsos-bug26-test'
Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$root\A\plugins\p", "$root\B\plugins\p", "$root\profilo\node_modules\@workspace-sm" | Out-Null
Set-Content "$root\A\plugins\p\fileA.txt" 'contenuto A'
Set-Content "$root\B\plugins\p\fileB.txt" 'contenuto B'

# La sequenza esatta di avvia.ps1: collega $link a $target, senza mai distruggere la destinazione.
function Collega($link, $target) {
    $item = Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
    if ($item) {
        $destinazione = if ($item.Target) { [IO.Path]::GetFullPath(@($item.Target)[0]) } else { $null }
        if ($item.LinkType -eq 'Junction' -and $destinazione -eq $target) { return }
        if ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink') { [System.IO.Directory]::Delete($link) }
        else { Remove-Item -LiteralPath $link -Recurse -Force }
    }
    New-Item -ItemType Junction -Path $link -Target $target | Out-Null
}

$link = "$root\profilo\node_modules\@workspace-sm\p"

# Caso 1: collegamento valido → riconosciuto e lasciato stare (skip).
New-Item -ItemType Junction -Path $link -Target "$root\A\plugins\p" | Out-Null
$prima = Get-Item -LiteralPath $link -Force
Collega $link ([IO.Path]::GetFullPath("$root\A\plugins\p"))
Verifica 'junction valido riconosciuto (skip)' ((Get-Item -LiteralPath $link -Force).Target -contains "$root\A\plugins\p")

# Caso 2: reso orfano spostando la destinazione → Get-Item lo trova comunque e lo ricrea.
Rename-Item "$root\A" "$root\A-spostata"
$item = Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
Verifica 'junction orfano trovato da Get-Item -LiteralPath' ($null -ne $item)
Rename-Item "$root\A-spostata" "$root\A"
Collega $link ([IO.Path]::GetFullPath("$root\A\plugins\p"))
Verifica 'junction orfano sostituito e funzionante' ((Get-Content "$link\fileA.txt") -eq 'contenuto A')

# Caso 3 (il pericolo del Bug #26): collegamento verso un'altra copia esistente →
# con Remove-Item -Recurse di PS 5.1 si sarebbe cancellato il contenuto di B.
[System.IO.Directory]::Delete($link)   # anche Remove-Item senza -Recurse va in errore sui junction (PS 5.1)
New-Item -ItemType Junction -Path $link -Target "$root\B\plugins\p" | Out-Null
Collega $link ([IO.Path]::GetFullPath("$root\A\plugins\p"))
Verifica 'collegamento verso altra copia riattaccato ad A' ((Get-Content "$link\fileA.txt") -eq 'contenuto A')
Verifica 'contenuto della copia B intatto' ((Get-Content "$root\B\plugins\p\fileB.txt") -eq 'contenuto B')

Remove-Item -Recurse -Force "$root\A", "$root\B", "$root\profilo"
if ($falliti) { Write-Host "$falliti verifiche fallite"; exit 1 }
Write-Host 'Tutte le verifiche superate'
