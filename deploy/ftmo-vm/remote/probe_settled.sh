#!/usr/bin/env bash
# Theory validation: pre-boot ONE terminal, let it fully settle (3 min on this
# 1GB box), then BARE attach — which never spawns/kills terminals.
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
PY='C:\Python310\python.exe'
T64="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/terminal64.exe"
cd "$HOME/apex-v4"

pkill -f terminal64[.]exe 2>/dev/null || true
wineserver -k 2>/dev/null || true
sleep 3
pkill -f '[X]vfb :1' 2>/dev/null || true
sleep 1
Xvfb :1 -screen 0 1280x800x16 >/tmp/xvfb1.log 2>&1 &
sleep 3
export DISPLAY=:1
xdpyinfo -display :1 >/dev/null 2>&1 && echo XVFB_OK || echo XVFB_FAIL

echo '── boot ONE terminal ──'
nohup wine "$T64" >/tmp/term_boot.log 2>&1 &
for i in $(seq 1 30); do pgrep -f terminal64[.]exe >/dev/null && break; sleep 2; done
pgrep -f terminal64[.]exe >/dev/null && echo TERMINAL_RUNNING || echo TERMINAL_NOT_RUNNING

echo '── settle 180s ──'
sleep 180
pgrep -f terminal64[.]exe >/dev/null && echo TERMINAL_STILL_ALIVE || echo TERMINAL_DIED

echo '── attach probes (bare first — never kills the terminal) ──'
timeout 320 wine "$PY" remote/probe_ipc2.py

echo '── post: terminal still alive? ──'
pgrep -f terminal64[.]exe >/dev/null && echo TERMINAL_SURVIVES || echo TERMINAL_GONE
echo SETTLED_PROBE_DONE
