#!/usr/bin/env bash
set -uo pipefail
export DISPLAY=:1
MT5_DIR="$HOME/.mt5/drive_c/Program Files/MetaTrader 5"
echo "=== terminal proc ==="; pgrep -fc 'terminal64[.]exe' || echo 0
echo "=== tmux windows ==="; tmux list-windows -t apex -F '#{window_name}:#{pane_dead}' 2>&1
echo "=== raw journal tail (today) ==="
iconv -f UTF-16LE -t UTF-8 "$MT5_DIR/logs/$(date -u +%Y%m%d).log" 2>/dev/null | tail -15
echo "=== screenshot ==="
scrot -o /tmp/state.png 2>/dev/null && echo SHOT_OK || echo NO_SCROT
