@echo off
setlocal
cd /d "%~dp0"
"runtime\python\python.exe" -X utf8 bootstrap.py launch
if errorlevel 1 pause
