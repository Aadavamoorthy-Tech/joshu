@echo off
setlocal
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo Backend virtual environment not found. See README.md for setup.
    pause
    exit /b 1
)

set "PORT=%~1"
if not defined PORT set "PORT=8000"
cd /d "%~dp0backend"
echo Starting backend on port %PORT%. Press Ctrl+C or close this window to stop it.
"%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port "%PORT%"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo Backend exited with code %RESULT%.
    pause
)
exit /b %RESULT%
