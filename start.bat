@echo off
title Apex Algo
color 0A
:: ─────────────────────────────────────────────────────────
::  APEX ALGO — start.bat   (run from the repo root)
::  One command: sets up everything (first run), then opens
::  the Web UI. All configuration is done IN the browser.
:: ─────────────────────────────────────────────────────────

echo.
echo   ============================================
echo            APEX ALGO
echo      IG Spread Betting Algorithm
echo   ============================================
echo.

:: ── Prereqs ────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (echo ERROR: Python not found. Install Python 3.11+ first. & pause & exit /b 1)
where node >nul 2>&1
if errorlevel 1 (echo ERROR: Node.js not found. Install Node.js 20+ first. & pause & exit /b 1)

:: ── 1. Python venv + deps (first run only) ─────────────
if not exist "venv\Scripts\python.exe" (
    echo   [setup] Creating Python virtual environment...
    python -m venv venv
)
if not exist "venv\.deps_installed" (
    echo   [setup] Installing Python dependencies...
    venv\Scripts\python.exe -m pip install --upgrade pip --quiet
    venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
    echo done> "venv\.deps_installed"
)

:: ── 2. Dashboard node modules (first run only) ─────────
if not exist "dashboard\node_modules" (
    echo   [setup] Installing dashboard dependencies ^(npm install^)...
    pushd dashboard
    call npm install --no-fund --no-audit
    popd
)

:: ── 3. Provision local config (login + state-server link) ─
echo   [setup] Preparing local configuration...
venv\Scripts\python.exe scripts\setup_local_env.py

:: ── 4. Launch state server + dashboard, open browser ───
echo.
echo   Starting the algo state server and the Web UI...
start "Apex State Server" cmd /k "venv\Scripts\python.exe main.py"
start "Apex Dashboard" cmd /k "cd dashboard && npm run dev"

echo   Waiting for the Web UI to compile...
timeout /t 9 /nobreak >nul
start "" http://localhost:3000

echo.
echo   ============================================
echo     Apex Algo is starting.
echo     Web UI : http://localhost:3000
echo     Log in, then complete onboarding in the browser.
echo     (Two windows opened: State Server + Dashboard.
echo      Close them to stop. This window can be closed.)
echo   ============================================
echo.
pause
