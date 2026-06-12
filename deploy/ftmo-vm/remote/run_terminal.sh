#!/usr/bin/env bash
# Boot the MT5 terminal in portable mode with the generated startup config
# (auto-login + ApexBridge EA). Owns ALL order execution.
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
export DISPLAY=:1
cd "$HOME/.mt5/drive_c/Program Files/MetaTrader 5"
exec wine terminal64.exe /portable '/config:config\apex_start.ini'
