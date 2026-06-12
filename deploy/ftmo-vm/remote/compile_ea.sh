#!/usr/bin/env bash
# Compile ApexBridge.mq5 to .ex5 with MetaEditor (headless under Wine).
set -uo pipefail
export WINEPREFIX="$HOME/.mt5"
export WINEDEBUG=-all
export DISPLAY=:1
MT5_DIR="$HOME/.mt5/drive_c/Program Files/MetaTrader 5"

mkdir -p "$MT5_DIR/MQL5/Experts"
cp "$HOME/apex-v4/ApexBridge.mq5" "$MT5_DIR/MQL5/Experts/ApexBridge.mq5"
cd "$MT5_DIR"
rm -f MQL5/Experts/compile.log
wine metaeditor64.exe /portable /compile:'MQL5\Experts\ApexBridge.mq5' /log:'MQL5\Experts\compile.log'
wineserver -w 2>/dev/null || true
iconv -f UTF-16LE -t UTF-8 "$MT5_DIR/MQL5/Experts/compile.log" 2>/dev/null | tail -4
if [ -f "$MT5_DIR/MQL5/Experts/ApexBridge.ex5" ]; then
  echo EA_COMPILE_OK
else
  echo EA_COMPILE_FAILED
  exit 1
fi
