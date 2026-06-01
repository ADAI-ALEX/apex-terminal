@echo off
title Apex Algo Engine
color 0A
:: ─────────────────────────────────────────────────────────
::  APEX ALGO — start.bat   (run from the repo root)
::  Runs ONLY the trading engine on this laptop. The Web UI
::  lives on Vercel — this opens it in your browser. All
::  configuration is done in the browser (cloud-relay mode).
:: ─────────────────────────────────────────────────────────

echo.
echo   ============================================
echo            APEX ALGO  -  Engine
echo   ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (echo ERROR: Python not found. Install Python 3.11+ first. & pause & exit /b 1)

:: ── Python venv + deps (first run only) ─────────────────
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

:: ── Provision config (pulls Vercel KV creds, login, Web UI URL) ─
echo   [setup] Syncing config from Vercel...
venv\Scripts\python.exe scripts\setup_local_env.py

:: ── Read the Web UI URL from .env (default Vercel deployment) ──
set "DASHBOARD_URL=https://apex-dashboard-pearl.vercel.app/"
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    if /i "%%a"=="DASHBOARD_URL" if not "%%b"=="" set "DASHBOARD_URL=%%b"
)

:: ── Open the Web UI (unless disabled) ───────────────────
if /i not "%DASHBOARD_URL%"=="none" (
    echo   Opening Web UI: %DASHBOARD_URL%
    start "" "%DASHBOARD_URL%"
)

:: ── Run the engine (this window) ────────────────────────
echo.
echo   Starting the trading engine. Leave this window open.
echo   Configure / monitor from the Web UI above (from any device).
echo   Press Ctrl-C here to stop trading.
echo.
venv\Scripts\python.exe main.py
pause
