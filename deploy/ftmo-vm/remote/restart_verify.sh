#!/usr/bin/env bash
# Clean single terminal boot + bridge verification. No wineserver -w (it can
# never return while the terminal intentionally runs).
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
export DISPLAY=:1
MT5_DIR="$HOME/.mt5/drive_c/Program Files/MetaTrader 5"

wine taskkill /IM terminal64.exe 2>/dev/null || true
sleep 15
pkill -f 'terminal64[.]exe' 2>/dev/null || true
sleep 3
tmux kill-window -t apex:mt5 2>/dev/null || true
tmux new-window -t apex -n mt5 "bash $HOME/apex-v4/remote/run_terminal.sh"

echo "── settling 240s ──"
sleep 240
echo "=== JOURNAL ==="
iconv -f UTF-16LE -t UTF-8 "$MT5_DIR/logs/$(date -u +%Y%m%d).log" 2>/dev/null | tail -6
echo "=== HEARTBEAT ==="
cat "$MT5_DIR/MQL5/Files/apex/heartbeat.txt" 2>/dev/null || echo NO_HB
echo "=== INDEX/CRYPTO SYMBOLS ==="
grep -E '500|BTC|SPX|NAS|US10|UST' "$MT5_DIR/MQL5/Files/apex/symbols_all.txt" 2>/dev/null | head -12 || echo NO_SYMBOL_DUMP
echo RESTART_VERIFY_DONE
