@echo off
rem Genera TUTTI i capitoli in MP3, riavviando la pipeline da sola se si blocca.
rem Si può chiudere e rilanciare: riparte dai capitoli mancanti.
chcp 65001 >nul
cd /d "%~dp0"
set "PY=%~dp0..\app\env-rocm\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0..\app\env\Scripts\python.exe"
"%PY%" -u esegui_tutto.py %*
pause
