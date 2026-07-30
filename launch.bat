@echo off
REM Photoreal launcher (Windows). Delegates to scripts\launch.ps1
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" %*
exit /b %ERRORLEVEL%
