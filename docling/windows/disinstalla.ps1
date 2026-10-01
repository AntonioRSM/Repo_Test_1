# Rimuove Docling Archivio (ambiente Python, modelli scaricati, collegamenti nel menu Start).
# NON tocca i tuoi progetti né i documenti convertiti. Python, Tesseract e LibreOffice restano installati.
Add-Type -AssemblyName System.Windows.Forms
$Base      = Join-Path $env:LOCALAPPDATA 'DoclingArchivio'
$MenuStart = Join-Path ([Environment]::GetFolderPath('Programs')) 'Docling Archivio'
$Modelli   = Join-Path $env:USERPROFILE '.cache\docling'

$r = [System.Windows.Forms.MessageBox]::Show(
    "Vuoi rimuovere Docling Archivio?`n`nVerranno eliminati:`n- $Base`n- $Modelli (modelli scaricati)`n- i collegamenti nel menu Start`n`nI tuoi progetti e i documenti convertiti NON vengono toccati.",
    'Disinstalla Docling Archivio', 'YesNo', 'Warning')
if ($r -ne 'Yes') { exit 0 }

Remove-Item $MenuStart -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $Modelli -Recurse -Force -ErrorAction SilentlyContinue
# questo script è dentro $Base: la cancellazione avviene dopo la sua chiusura
Start-Process cmd.exe -ArgumentList "/c timeout /t 2 >nul & rmdir /s /q `"$Base`"" -WindowStyle Hidden
[System.Windows.Forms.MessageBox]::Show('Docling Archivio è stato rimosso.', 'Disinstalla Docling Archivio') | Out-Null
