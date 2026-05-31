@echo off
title Apex Algo
color 0A
setlocal enabledelayedexpansion
:: ─────────────────────────────────────────────────────────
::  APEX ALGO — start.bat   (run from the repo root)
::  Each dependency is checked independently, so a partial
::  setup (e.g. venv exists but node_modules don't) self-heals.
:: ─────────────────────────────────────────────────────────

echo.
echo   ============================================
echo            APEX ALGO  v1.0
echo      IG Spread Betting Algorithm
echo   ============================================
echo.

:: ── Prereqs ────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (echo ERROR: Python not found. Install Python 3.11+ first. & pause & exit /b 1)
where node >nul 2>&1
if errorlevel 1 (echo ERROR: Node.js not found. Install Node.js 20+ first. & pause & exit /b 1)

:: ── 1. Python venv ─────────────────────────────────────
if not exist "venv\Scripts\python.exe" (
    echo   [setup] Creating Python virtual environment...
    python -m venv venv
)
if not exist "venv\.deps_installed" (
    echo   [setup] Installing Python dependencies...
    call venv\Scripts\activate.bat
    python -m pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    call venv\Scripts\deactivate.bat
    echo done> "venv\.deps_installed"
)

:: ── 2. Dashboard node modules ──────────────────────────
if not exist "dashboard\node_modules" (
    echo   [setup] Installing dashboard dependencies ^(npm install^)...
    pushd dashboard
    call npm install --no-fund --no-audit
    popd
)

:: ── 3. Python .env ─────────────────────────────────────
if not exist ".env" (
    echo   [setup] Creating .env from template...
    copy /Y .env.example .env >nul
    echo.
    echo   --------------------------------------------
    echo    ACTION REQUIRED: fill in your .env
    echo    Location: %CD%\.env
    echo    Add IG credentials + ANTHROPIC_API_KEY
    echo    ^(Leaving them blank runs in safe PAPER mode^)
    echo   --------------------------------------------
    echo.
    start notepad .env
    echo   Press any key after saving .env...
    pause >nul
)

:: ── 4. Dashboard .env.local (with generated AUTH_SECRET) ─
if not exist "dashboard\.env.local" (
    echo   [setup] Creating dashboard\.env.local with a generated AUTH_SECRET...
    copy /Y dashboard\.env.example dashboard\.env.local >nul
    node -e "const fs=require('fs');const p='dashboard/.env.local';let s=fs.readFileSync(p,'utf8');s=s.replace(/AUTH_SECRET=.*/,'AUTH_SECRET='+require('crypto').randomBytes(32).toString('base64'));fs.writeFileSync(p,s);"
    echo   Set DASHBOARD_USERNAME / DASHBOARD_PASSWORD in dashboard\.env.local before logging in.
)

:: ── MAIN MENU ──────────────────────────────────────────
:menu
echo.
echo   +--------------------------------------+
echo   ^|  What do you want to do?             ^|
echo   ^|                                      ^|
echo   ^|  [1] Start algo (DEMO/PAPER mode)    ^|
echo   ^|  [2] Start algo (LIVE mode)          ^|
echo   ^|  [3] Open dashboard (localhost:3000) ^|
echo   ^|  [4] Start algo + dashboard          ^|
echo   ^|  [5] Check status                    ^|
echo   ^|  [6] Exit                            ^|
echo   +--------------------------------------+
set /p choice="  Enter choice: "

if "%choice%"=="1" goto start_demo
if "%choice%"=="2" goto start_live
if "%choice%"=="3" goto open_dashboard
if "%choice%"=="4" goto start_both
if "%choice%"=="5" goto check_status
if "%choice%"=="6" exit /b 0
goto menu

:start_demo
echo   Starting Apex Algo in DEMO/PAPER mode...
set "IG_ACC_TYPE=DEMO"
call venv\Scripts\activate.bat && python main.py
goto menu

:start_live
echo.
echo   ============================================
echo     WARNING: LIVE ACCOUNT MODE
echo     Real money will be at risk.
echo   ============================================
set /p confirm="  Type CONFIRM to proceed: "
if not "%confirm%"=="CONFIRM" goto menu
set "IG_ACC_TYPE=LIVE"
call venv\Scripts\activate.bat && python main.py
goto menu

:open_dashboard
echo   Starting dashboard on localhost:3000...
start "" http://localhost:3000
pushd dashboard
call npm run dev
popd
goto menu

:start_both
echo   Starting algo (DEMO/PAPER) + dashboard...
:: DEMO is the default in config.py, so no env var needed here (avoids the
:: classic "set VAR=DEMO &&" trailing-space bug inside a cmd /k string).
start "Apex Algo" cmd /k "call venv\Scripts\activate.bat && python main.py"
timeout /t 4 /nobreak >nul
start "Apex Dashboard" cmd /k "cd dashboard && npm run dev"
timeout /t 6 /nobreak >nul
start "" http://localhost:3000
echo   Dashboard opening at http://localhost:3000 (give it ~15s to compile).
goto menu

:check_status
python -c "import urllib.request,json,os; s=os.getenv('VPS_SECRET','change-me'); req=urllib.request.Request('http://localhost:8080/health', headers={'X-Apex-Secret':s}); print('Algo:', json.load(urllib.request.urlopen(req,timeout=3))['status'])" 2>nul || echo   Algo not running.
goto menu
