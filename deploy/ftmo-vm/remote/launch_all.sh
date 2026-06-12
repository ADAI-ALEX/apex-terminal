#!/usr/bin/env bash
# Launch the full V4 bridge stack in one tmux session:
#   xvfb -> MT5 terminal (portable, auto-login, ApexBridge EA) -> native legs.
set -euo pipefail
ENVF="$HOME/apex-v4/.env"
[ -f "$ENVF" ] || { echo "ERROR: ~/apex-v4/.env missing — fill creds first" >&2; exit 1; }

bash "$HOME/apex-v4/remote/gen_start_ini.sh"
MT5_DIR="$HOME/.mt5/drive_c/Program Files/MetaTrader 5"
[ -f "$MT5_DIR/MQL5/Experts/ApexBridge.ex5" ] || bash "$HOME/apex-v4/remote/compile_ea.sh"

tmux kill-session -t apex 2>/dev/null || true
# a stale Xvfb :1 makes the new one exit instantly, killing the whole session
pkill -f '[X]vfb :1' 2>/dev/null || true
sleep 1
tmux new-session  -d -s apex -n xvfb "Xvfb :1 -screen 0 1280x800x16"
sleep 2
tmux new-window   -t apex    -n mt5 "bash $HOME/apex-v4/remote/run_terminal.sh"
echo "waiting 150s for terminal boot + FTMO login + EA start…"
sleep 150
# auto-confirm the pre-filled login dialog if this build shows it at boot
DISPLAY=:1 xdotool key Return 2>/dev/null || true
sleep 3
DISPLAY=:1 xdotool mousemove 618 465 click 1 2>/dev/null || true
sleep 20
bash "$HOME/apex-v4/remote/respawn_legs.sh"

echo "── stack up ──"
tmux ls
echo "bridge heartbeat:"
tail -2 "$MT5_DIR/MQL5/Files/apex/heartbeat.txt" 2>/dev/null || echo "  (not yet — EA may still be starting)"
echo "attach:  tmux attach -t apex"
