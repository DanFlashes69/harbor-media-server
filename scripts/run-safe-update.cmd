@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0safe-update-media-stack.ps1"
endlocal
