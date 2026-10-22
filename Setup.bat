@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\Install.ps1"
if errorlevel 1 (echo Setup failed. Please read the error above. & pause & exit /b 1)
pause
