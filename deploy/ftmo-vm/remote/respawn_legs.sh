#!/usr/bin/env bash
# (Re)spawn the two strategy-leg tmux windows. Safe to run any time the
# apex session exists; quoting lives HERE, never inline over SSH.
set -uo pipefail
tmux has-session -t apex 2>/dev/null || { echo NO_SESSION; exit 1; }
for leg in btc us500; do
  tmux kill-window -t apex:"$leg" 2>/dev/null || true
  tmux new-window -t apex -n "$leg" "bash $HOME/apex-v4/remote/run_leg.sh $leg"
  # stagger: let the first leg win the MT5 IPC handshake before the second piles on
  [ "$leg" = btc ] && sleep 45
done
tmux list-windows -t apex -F '#{window_name}'
echo LEGS_RESPAWNED
