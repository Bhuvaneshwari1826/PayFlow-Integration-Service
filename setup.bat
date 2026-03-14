@echo off
REM ============================================================
REM  Takaada Integration Service — Windows Local Setup Helper
REM  Run this from the project root in Command Prompt or PowerShell.
REM  Requires: Python 3.12+, PostgreSQL 14+, Git
REM ============================================================

echo.
echo === Takaada Integration Service - Windows Setup ===
echo.

REM --- Step 1: Create virtual environment ---
IF NOT EXIST "venv" (
    echo [1/5] Creating virtual environment...
    python -m venv venv
) ELSE (
    echo [1/5] Virtual environment already exists, skipping.
)

REM --- Step 2: Activate and install deps ---
echo [2/5] Installing dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet

REM --- Step 3: Copy .env if not present ---
IF NOT EXIST ".env" (
    echo [3/5] Creating .env from example...
    copy .env.example .env
    echo       .env created. Edit it if your Postgres credentials differ from defaults.
) ELSE (
    echo [3/5] .env already exists, skipping.
)

REM --- Step 4: Create DB and run migrations ---
echo [4/5] Running database migrations...
echo       (Make sure PostgreSQL is running and the 'takaada' database exists.)
echo       To create it: psql -U postgres -c "CREATE DATABASE takaada;"
echo.
alembic upgrade head
IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Migration failed. Check that:
    echo   1. PostgreSQL is running
    echo   2. The 'takaada' database exists
    echo   3. DATABASE_URL in .env matches your Postgres credentials
    pause
    exit /b 1
)

REM --- Step 5: Instructions for starting services ---
echo.
echo [5/5] Setup complete!
echo.
echo To start the service, open TWO terminal windows and run:
echo.
echo   Terminal 1 (Mock API):
echo     venv\Scripts\activate
echo     uvicorn app.integrations.mock_server:app --port 8001
echo.
echo   Terminal 2 (Main Service):
echo     venv\Scripts\activate
echo     uvicorn app.main:app --reload --port 8000
echo.
echo Then trigger the first sync:
echo   PowerShell: Invoke-RestMethod -Method POST -Uri http://localhost:8000/api/v1/sync/run
echo   curl:       curl -X POST http://localhost:8000/api/v1/sync/run
echo.
echo API docs: http://localhost:8000/docs
echo.
pause
