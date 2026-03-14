# setup.ps1 — Takaada Integration Service Windows Setup
# Run from the project root:  .\setup.ps1
# Requires: Python 3.12+, PostgreSQL 14+

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Takaada Integration Service - Windows Setup ===" -ForegroundColor Cyan
Write-Host ""

# --- Step 1: Virtual environment ---
if (-Not (Test-Path "venv")) {
    Write-Host "[1/5] Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
} else {
    Write-Host "[1/5] Virtual environment already exists." -ForegroundColor Green
}

# --- Step 2: Activate and install deps ---
Write-Host "[2/5] Installing dependencies..." -ForegroundColor Yellow
& venv\Scripts\Activate.ps1
pip install -r requirements.txt --quiet
Write-Host "      Dependencies installed." -ForegroundColor Green

# --- Step 3: Copy .env ---
if (-Not (Test-Path ".env")) {
    Write-Host "[3/5] Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item .env.example .env
    Write-Host "      .env created. Edit if your Postgres credentials differ." -ForegroundColor Green
} else {
    Write-Host "[3/5] .env already exists." -ForegroundColor Green
}

# --- Step 4: Migrations ---
Write-Host "[4/5] Running database migrations..." -ForegroundColor Yellow
Write-Host "      Make sure PostgreSQL is running and 'takaada' DB exists."
Write-Host "      To create it: psql -U postgres -c `"CREATE DATABASE takaada;`""
Write-Host ""

try {
    alembic upgrade head
    Write-Host "      Migrations applied successfully." -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "ERROR: Migration failed. Check:" -ForegroundColor Red
    Write-Host "  1. PostgreSQL is running (check Services or pgAdmin)"
    Write-Host "  2. 'takaada' database exists"
    Write-Host "  3. DATABASE_URL in .env matches your credentials"
    Write-Host ""
    Write-Host "Default .env expects: takaada / takaada @ localhost:5433/takaada"
    exit 1
}

# --- Step 5: Summary ---
Write-Host ""
Write-Host "[5/5] Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Start the service with TWO terminals:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Terminal 1 - Mock Accounting API:" -ForegroundColor White
Write-Host "    venv\Scripts\Activate.ps1"
Write-Host "    uvicorn app.integrations.mock_server:app --port 8001"
Write-Host ""
Write-Host "  Terminal 2 - Main Service:" -ForegroundColor White
Write-Host "    venv\Scripts\Activate.ps1"
Write-Host "    uvicorn app.main:app --reload --port 8000"
Write-Host ""
Write-Host "Trigger the first sync:" -ForegroundColor Cyan
Write-Host "  Invoke-RestMethod -Method POST -Uri http://localhost:8000/api/v1/sync/run"
Write-Host ""
Write-Host "API docs: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""
