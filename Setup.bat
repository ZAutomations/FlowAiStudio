@echo off
setlocal
cd /d "%~dp0"
"runtime\python\python.exe" -X utf8 bootstrap.py setup
if errorlevel 1 (
 echo Setup failed. Existing projects and models were retained.
 pause
 exit /b 1
)
echo Setup completed. Open FlowAiStudio.bat.
pause
