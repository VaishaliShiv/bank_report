@echo off
REM One-step setup: creates the venv, installs dependencies, writes .env,
REM and tests the connection. Run this once, then use run_api.bat.
cd /d "%~dp0"

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv || goto :err
    echo Installing dependencies. This takes about a minute...
    .venv\Scripts\python -m pip install --quiet --upgrade pip
    .venv\Scripts\pip install --quiet -r requirements.txt || goto :err
)

.venv\Scripts\python setup_env.py
pause
goto :eof

:err
echo.
echo Setup failed. Is Python 3.12+ installed and on PATH?
echo Check with:  python --version
pause
