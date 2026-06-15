#!/usr/bin/env bash
# Regenerate the startup config WITH credentials, gracefully restart the
# terminal, and report whether headless config-login now authorizes.
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
export DISPLAY=:1
MT5_DIR="$HOME/.mt5/drive_c/Program Files/MetaTrader 5"
APEX="$MT5_DIR/MQL5/Files/apex"

echo '── precondition: servers.dat present? ──'
ls -la "$MT5_DIR/config/servers.dat" 2>/dev/null || echo 'WARNING: servers.dat MISSING — config login cannot resolve server'

echo '── regenerate config with creds ──'
bash "$HOME/apex-v4/remote/gen_start_ini.sh"

echo '── graceful terminal restart ──'
wine taskkill /IM terminal64.exe 2>/dev/null || true
sleep 15
pkill -f 'terminal64[.]exe' 2>/dev/null || true
sleep 3
# fresh heartbeat marker so we can prove the EA wrote a NEW one
rm -f "$APEX/heartbeat.txt"
tmux kill-window -t apex:mt5 2>/dev/null || true
tmux new-window -t apex -n mt5 "bash $HOME/apex-v4/remote/run_terminal.sh"

echo '── settling 200s ──'
sleep 200

echo '=== AUTHORIZATION (journal) ==='
iconv -f UTF-16LE -t UTF-8 "$MT5_DIR/logs/$(date -u +%Y%m%d).log" 2>/dev/null \
  | grep -iE 'authoriz|login|synchroniz|account has been' | tail -6
echo '=== HEARTBEAT ==='
if [ -f "$APEX/heartbeat.txt" ]; then
  cat "$APEX/heartbeat.txt"
else
  echo NO_HB
fi
echo '=== SP500m FEED ==='
head -3 "$APEX/sym_SP500m.txt" 2>/dev/null || echo NO_FEED
echo APPLY_CREDS_DONE
