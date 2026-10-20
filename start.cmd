@echo off
rem Starts RAG Vault Studio. Pass --hidden to start in the system tray.
cd /d "%~dp0desktop"
node scripts\ensure-build.cjs || (pause & exit /b 1)
start "" "%~dp0desktop\node_modules\electron\dist\electron.exe" . %*
