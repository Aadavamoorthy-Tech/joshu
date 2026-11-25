@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-servers.ps1" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo Server launcher exited with code %RESULT%.
    pause
)
exit /b %RESULT%
