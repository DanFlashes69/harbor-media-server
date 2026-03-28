@echo off
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0backup-media-stack.ps1"
exit /b %ERRORLEVEL%
