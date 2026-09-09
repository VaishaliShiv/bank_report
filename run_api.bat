@echo off
REM ===================================================================
REM  Payment Reconciliation API - Windows launcher
REM  Starts the dashboard. Leave the window open while you use it.
REM ===================================================================
cd /d "%~dp0api-service"

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv || goto :err
    .venv\Scripts\python -m pip install --quiet --upgrade pip
    echo Installing dependencies...
    .venv\Scripts\pip install --quiet -r requirements.txt || goto :err
)

if not exist .env if not exist ..\.env (
    echo.
    echo   ERROR: .env not found.
    echo   Copy .env.example to .env and paste your storage connection string.
    echo.
    pause
    exit /b 1
)

echo.
echo   Payment Reconciliation API
echo   ---------------------------------------------
echo   Dashboard:  http://localhost:8000
echo   API:        http://localhost:8000/api/dates
echo.
echo   Keep this window open. Ctrl+C to stop.
echo.
.venv\Scripts\uvicorn api.main:app --host 127.0.0.1 --port 8000
goto :eof

:err
echo.
echo   Setup failed. Is Python 3.12+ installed and on PATH?
pause
