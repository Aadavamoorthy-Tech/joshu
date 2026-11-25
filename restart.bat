@echo off
REM Restart both backend and frontend servers
REM Just double-click this file or run: restart.bat

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "restart.ps1"
pause
