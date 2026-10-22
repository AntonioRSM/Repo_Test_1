# Logica di collegamento dei plugin Workspace al profilo dsh (Bug #26).
# Condivisa tra avvia.ps1 e tools/testa-junction.ps1 (Miglioramento #19): il test
# esercita QUESTO codice, non una copia.
#
# Bug #26: Test-Path SEGUE il collegamento e restituisce $false per un junction orfano
# (destinazione spostata/cancellata): New-Item falliva a ogni avvio. Peggio: Remove-Item
# -Recurse in Windows PowerShell 5.1 cancella il CONTENUTO della cartella di destinazione
# di un junction — con due copie del progetto si distruggevano i plugin dell'altra.
# Get-Item -LiteralPath non segue il collegamento; [System.IO.Directory]::Delete toglie
# solo il collegamento, senza toccare la destinazione.

function Installa-PluginWorkspace {
    param(
        [Parameter(Mandatory = $true)][string]$Profilo,   # cartella del profilo dsh
        [Parameter(Mandatory = $true)][string]$Harness    # cartella harness della copia attiva
    )
    $scope = Join-Path $Profilo 'node_modules\@workspace-sm'
    New-Item -ItemType Directory -Force -Path $scope | Out-Null
    foreach ($p in 'dsh-workspace-brand', 'dsh-workspace-it') {
        $link = Join-Path $scope $p
        $target = [IO.Path]::GetFullPath((Join-Path $Harness "plugins\$p"))
        $item = Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
        if ($item) {
            $destinazione = if ($item.Target) { [IO.Path]::GetFullPath(@($item.Target)[0]) } else { $null }
            if ($item.LinkType -eq 'Junction' -and $destinazione -eq $target) { continue }
            if ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink') { [System.IO.Directory]::Delete($link) }
            else { Remove-Item -LiteralPath $link -Recurse -Force }   # cartella reale, non collegamento
        }
        New-Item -ItemType Junction -Path $link -Target $target | Out-Null
    }
}
