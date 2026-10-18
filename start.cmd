@echo off
rem Starts RAG Vault Studio. Pass --hidden to start in the system tray.
cd /d "%~dp0desktop"
if not exist dist\index.html call npm run build
start "" "%~dp0desktop\node_modules\electron\dist\electron.exe" . %*
