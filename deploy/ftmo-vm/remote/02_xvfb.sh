#!/usr/bin/env bash
# Headless display stack + session tooling.
set -euo pipefail
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y xvfb tmux winbind
echo "xvfb + tmux installed"
Xvfb -help >/dev/null 2>&1 && echo "Xvfb OK"
tmux -V
