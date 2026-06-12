#!/usr/bin/env bash
# THE consolidation boot: correct symbols, ONE Xvfb, ONE terminal, verify.
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
export DISPLAY=:1
MT5_DIR="$HOME/.mt5/drive_c/Program Files/MetaTrader 5"

echo '── fix symbols in .env (server truth: SP500m; no BTC CFD on this demo) ──'
sed -i 's/^US500_SYMBOL=.*/US500_SYMBOL=SP500m/' "$HOME/apex-v4/.env"
grep -E '^(US500_SYMBOL|BTC_SYMBOL)=' "$HOME/apex-v4/.env"
bash "$HOME/apex-v4/remote/gen_start_ini.sh"

echo '── quiesce: all terminals, all displays ──'
wine taskkill /IM terminal64.exe 2>/dev/null || true
sleep 12
pkill -f 'terminal64[.]exe' 2>/dev/null || true
pkill -f '[X]vfb' 2>/dev/null || true
sleep 3

echo '── one display, one terminal ──'
tmux respawn-window -k -t apex:xvfb 'Xvfb :1 -screen 0 1280x800x16' 2>/dev/null \
  || tmux new-window -t apex -n xvfb 'Xvfb :1 -screen 0 1280x800x16'
sleep 3
tmux respawn-window -k -t apex:mt5 "bash $HOME/apex-v4/remote/run_terminal.sh" 2>/dev/null \
  || tmux new-window -t apex -n mt5 "bash $HOME/apex-v4/remote/run_terminal.sh"

echo '── settling 280s ──'
sleep 280
echo '=== JOURNAL ==='
iconv -f UTF-16LE -t UTF-8 "$MT5_DIR/logs/$(date -u +%Y%m%d).log" 2>/dev/null | tail -6
echo '=== HEARTBEAT ==='
cat "$MT5_DIR/MQL5/Files/apex/heartbeat.txt" 2>/dev/null || echo NO_HB
echo '=== SP500m FEED ==='
cat "$MT5_DIR/MQL5/Files/apex/sym_SP500m.txt" 2>/dev/null | head -4 || echo NO_SP500m_FILE
echo '=== PROCS ==='
pgrep -fc 'terminal64[.]exe' || true
FINAL=BOOT; echo "${FINAL}_DONE"
