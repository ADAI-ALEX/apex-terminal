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

# [Common] auto-login: the documented MT5 headless login. This was a no-op on
# the FIRST attempts because servers.dat had no FTMO records, so the terminal
# could not resolve SERVER -> an access point. The one-time GUI login
# (File -> Open an Account) populated servers.dat, so config-file login now
# resolves and authorizes headlessly — no GUI/xdotool needed on subsequent boots.
cat > "$CFGDIR/apex_start.ini" <<EOF
[Common]
Login=$LOGIN
Password=$PASS
Server=${SERVER:-FTMO-Demo}
ProxyEnable=0
KeepPrivate=1
NewsEnable=0
CertInstall=0
AutoConfiguration=0
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

# Mirror into common.ini too: under Wine the /config: switch is read
# inconsistently, but the terminal ALWAYS reads config\common.ini at startup,
# so the credentials land via at least one path. Same account as the saved
# session => no "account has been changed" trading lockout.
[ -f "$CFGDIR/common.ini" ] && [ ! -f "$CFGDIR/common.ini.orig" ] \
  && cp "$CFGDIR/common.ini" "$CFGDIR/common.ini.orig"
cp "$CFGDIR/apex_start.ini" "$CFGDIR/common.ini"
chmod 600 "$CFGDIR/common.ini"
echo "start ini (+creds) + common.ini + EA preset written (login $LOGIN @ ${SERVER:-FTMO-Demo})"
