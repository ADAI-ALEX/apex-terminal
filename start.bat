@echo off
title Apex Algo
color 0A
setlocal enabledelayedexpansion
:: ─────────────────────────────────────────────────────────
::  APEX ALGO — start.bat
::  First run: installs Python deps, Node deps, creates .env
::  Subsequent runs: launch menu (algo / dashboard / both)
::  Run from the repo root.
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

:: ── First-time setup ───────────────────────────────────
if not exist "venv" (
    echo   [SETUP] First run detected — installing dependencies...
    echo.
    echo   [1/4] Creating Python virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    python -m pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    call venv\Scripts\deactivate.bat

    echo   [2/4] Installing dashboard dependencies...
    pushd dashboard
    call npm install --silent
    popd

    if not exist ".env" (
        echo   [3/4] Creating .env from template...
        copy /Y .env.example .env >nul
        echo.
        echo   --------------------------------------------
        echo    ACTION REQUIRED: fill in your .env
        echo    Location: %CD%\.env
        echo    Add IG credentials + ANTHROPIC_API_KEY
        echo   --------------------------------------------
        echo.
        start notepad .env
        echo   Press any key after saving .env...
        pause >nul
    )
    echo   [4/4] Setup complete.
    echo.
)

:: ── Main menu ──────────────────────────────────────────
:menu
echo.
echo   +--------------------------------------+
echo   ^|  What do you want to do?             ^|
echo   ^|                                      ^|
echo   ^|  [1] Start algo (DEMO mode)          ^|
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
echo   Starting Apex Algo in DEMO mode...
set IG_ACC_TYPE=DEMO
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
set IG_ACC_TYPE=LIVE
call venv\Scripts\activate.bat && python main.py
goto menu

:open_dashboard
echo   Starting dashboard on localhost:3000...
start http://localhost:3000
pushd dashboard
call npm run dev
popd
goto menu

:start_both
echo   Starting algo (DEMO) + dashboard...
start "Apex Algo" cmd /k "set IG_ACC_TYPE=DEMO && call venv\Scripts\activate.bat && python main.py"
timeout /t 3 /nobreak >nul
start "Apex Dashboard" cmd /k "cd dashboard && npm run dev"
timeout /t 5 /nobreak >nul
start http://localhost:3000
echo   Dashboard opened at http://localhost:3000
goto menu

:check_status
python -c "import urllib.request,json,os; s=os.getenv('VPS_SECRET','change-me-to-a-long-random-string'); req=urllib.request.Request('http://localhost:8080/health', headers={'X-Apex-Secret':s}); print('Algo:', json.load(urllib.request.urlopen(req,timeout=3))['status'])" 2>nul || echo   Algo not running.
goto menu
