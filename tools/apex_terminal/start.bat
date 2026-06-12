@echo off
title APEX COMMAND TERMINAL
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [FATAL] Python 3.10+ not found on PATH. Install from python.org and retry.
  pause & exit /b 1
)

echo [setup] checking local dependencies...
python -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo [setup] installing fastapi + uvicorn ^(one-time^)...
  python -m pip install --quiet --disable-pip-version-check fastapi "uvicorn[standard]"
  if errorlevel 1 ( echo [FATAL] pip install failed & pause & exit /b 1 )
)

if not exist "ssh-key-2026-06-10.key" (
  echo [WARN] ssh-key-2026-06-10.key not found next to start.bat — SSH link will fail.
)

echo [boot] APEX COMMAND TERMINAL  --^>  http://localhost:8000   (Ctrl+C to shut down)
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start "" http://localhost:8000"
python -m uvicorn app:app --app-dir apex_terminal --host 127.0.0.1 --port 8000 --log-level warning
