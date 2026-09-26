@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Clear PSModulePath so Windows PowerShell 5.1 loads its own modules even when started from PowerShell 7
set "PSModulePath="
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0improve-localai.ps1" %*
pause
