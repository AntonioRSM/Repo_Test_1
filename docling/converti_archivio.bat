@echo off
REM Converte un progetto con Docling (in WSL2).
REM Uso: trascina la cartella del progetto su questo file, oppure
REM      converti_archivio.bat "D:\RAG\progetto-alfa"
setlocal
if "%~1"=="" (
    echo Uso: converti_archivio.bat "D:\RAG\progetto-alfa"
    echo La cartella deve contenere la sottocartella "originali".
    pause
    exit /b 1
)
wsl.exe -e bash -lc "~/.local/bin/converti-archivio '%~f1'"
pause
