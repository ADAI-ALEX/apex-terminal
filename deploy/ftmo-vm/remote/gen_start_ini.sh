#!/usr/bin/env bash
# Build the MT5 startup config (auto-login + ApexBridge EA autostart) from
# ~/apex-v4/.env. Credentials never leave the VM.
set -euo pipefail
ENVF="$HOME/apex-v4/.env"
[ -f "$ENVF" ] || { echo "ERROR: $ENVF missing"; exit 1; }
get() { grep -E "^$1=" "$ENVF" | head -1 | cut -d= -f2- | tr -d '\r'; }

LOGIN=$(get MT5_LOGIN); PASS=$(get MT5_PASSWORD); SERVER=$(get MT5_SERVER)
BTC=$(get BTC_SYMBOL); US=$(get US500_SYMBOL)
[ -n "$LOGIN" ] && [ -n "$PASS" ] || { echo "ERROR: MT5_LOGIN/MT5_PASSWORD empty in .env"; exit 1; }

CFGDIR="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/config"
mkdir -p "$CFGDIR"

cat > "$CFGDIR/apexbridge.set" <<EOF
InpSymbols=${BTC:-BTCUSD},${US:-US500}
InpBars=420
InpDealsDays=50
EOF

# NO [Common] credentials here: a Login= section makes the terminal attempt a
# config-file login (silently broken on this build under Wine) INSTEAD of its
# native auto-reconnect to the account saved via the one-time GUI login.
cat > "$CFGDIR/apex_start.ini" <<EOF
[Experts]
AllowLiveTrading=1
AllowDllImport=0
Enabled=1
[StartUp]
Expert=ApexBridge
ExpertParameters=apexbridge.set
Symbol=EURUSD
Period=H1
EOF
# Chart symbol is EURUSD deliberately: FX majors always synchronize, so the EA
# initializes even if index symbol names differ — the EA bridges InpSymbols
# regardless of which chart hosts it.
chmod 600 "$CFGDIR/apex_start.ini"

# Drop any credential-bearing common.ini we previously wrote (it interferes the
# same way); the terminal regenerates its own.
[ -f "$CFGDIR/common.ini.orig" ] && cp "$CFGDIR/common.ini.orig" "$CFGDIR/common.ini" \
  || rm -f "$CFGDIR/common.ini"
echo "start ini (no-creds) + EA preset written"
