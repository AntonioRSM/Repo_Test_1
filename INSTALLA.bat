@echo off
REM Installa (o aggiorna) RAG Vault Studio e crea il collegamento nel menu Start.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\installa.ps1" %*
