# Apex V4 Institutional — FTMO MT5 deployment (Oracle VM)

Two-pillar validated frontier (Phase 5.4): **BTC 4H** (`global_macro_v4.py`,
Crypto State V2 stack, CHALLENGE_MODE switch) + **US500 1H**
(`auction_flow_v5_1_hybrid.py`, velocity-gated auction MR).
Blend evidence: 2.27%/mo all-climate, worst dDD 3.70 / tDD 8.30, MC 89.5%.

## Layout (VM: `~/apex-v4/`)
- `apex_mt5.py` — shared MT5 execution engine (faithful indicator ports; owns ALL orders)
- `global_macro_v4.py` — BTC leg (reads `CHALLENGE_MODE` from `.env`)
- `auction_flow_v5_1_hybrid.py` — US500 leg (same in both modes)
- `.env.template` → copy to `.env`, fill FTMO demo creds (never commit)
- `remote/` — provisioning + launch scripts (already run by the deploy agent)

## One-time setup status
1. `remote/01_swap.sh` — 2GB swapfile (1GB-RAM VM survival)
2. `remote/02_xvfb.sh` — xvfb + tmux + winbind
3. `remote/03_mt5_install.sh` — official MetaQuotes `mt5linux.sh` (download.mql5.com), silent under xvfb
4. `remote/04_winpython.sh` — Windows Python 3.10.11 inside `~/.mt5` Wine prefix
5. `remote/05_pip.sh` — `MetaTrader5` + numpy into that Python

## Launch
```bash
cp ~/apex-v4/.env.template ~/apex-v4/.env && nano ~/apex-v4/.env   # fill creds
bash ~/apex-v4/remote/launch_all.sh
tmux attach -t apex        # windows: xvfb | mt5 | btc | us500
```
Logs: `~/apex-v4/global_macro_v4.log`, `~/apex-v4/auction_flow_v5_1.log`.

## Live-fidelity caveats (accepted for the demo run)
- `flow_norm` uses REAL Binance perp taker imbalance (seed-faithful) with a
  CLV-CVD proxy fallback if Binance is unreachable from the VM.
- FTMO server time is EET (`SERVER_UTC_OFFSET_HOURS=3` summer / `2` winter).
- US500/BTC symbols may differ per FTMO server — check Market Watch.
- Flip `CHALLENGE_MODE=false` the day the account is funded.
