#!/usr/bin/env bash
# Flip prefix to Windows 10, guarantee a live Xvfb :1, pre-boot the terminal
# on it, then probe both attach modes.
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
PY='C:\Python310\python.exe'
T64="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/terminal64.exe"
cd "$HOME/apex-v4"

echo '── quiesce ──'
pkill -f terminal64[.]exe 2>/dev/null || true
wineserver -k 2>/dev/null || true
sleep 3

echo '── fresh Xvfb :1 ──'
pkill -f '[X]vfb :1' 2>/dev/null || true
sleep 1
Xvfb :1 -screen 0 1280x800x16 >/tmp/xvfb1.log 2>&1 &
sleep 3
export DISPLAY=:1
if xdpyinfo -display :1 >/dev/null 2>&1; then echo 'Xvfb :1 VERIFIED ALIVE'; else echo 'Xvfb :1 DEAD'; fi

echo '── prefix → win10 ──'
wine winecfg /v win10 2>/dev/null
wineserver -w || true
wine reg query 'HKLM\Software\Microsoft\Windows NT\CurrentVersion' /v CurrentBuild 2>/dev/null | tail -2

echo '── pre-boot terminal on :1 ──'
nohup wine "$T64" >/dev/null 2>&1 &
sleep 80

echo '── probe both attach modes ──'
timeout 400 wine "$PY" remote/probe_ipc2.py

pkill -f terminal64[.]exe 2>/dev/null || true
echo WIN10_PROBE_DONE
