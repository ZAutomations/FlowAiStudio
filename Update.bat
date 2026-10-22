@echo off
setlocal
cd /d "%~dp0"
set "FLOW_GIT=git"
where git >nul 2>nul
if errorlevel 1 set "FLOW_GIT=%ProgramFiles%\Git\cmd\git.exe"
"%FLOW_GIT%" pull --ff-only
if errorlevel 1 (echo Update stopped. No local files were reset. & pause & exit /b 1)
call "%~dp0Setup.bat"
