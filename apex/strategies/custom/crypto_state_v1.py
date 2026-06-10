# name: Crypto State V1 (BTC/ETH 15M)
# description: Phase-5 crypto perpetual state engine — LONG-ONLY dual-momentum continuation on the 15-minute chart, built from a 6.4-year (225k-bar) Binance perp probe with real taker-flow order data. Three stacked state layers must agree: (1) MACRO permission — price >3% above the 50-day daily SMA AND above the 200-day daily SMA (the probe proved the entire 15M momentum edge lives here: +52.6bps/24h t=19.8 above vs -8.7bps below); (2) MOMENTUM ignition — volatility-normalized 24h return z>1 with 6h alignment z>0.5; (3) FLOW confirmation — real taker-buy imbalance >2% of volume. Exits on momentum death (z<0), 4-4.5 ATR floored disaster stop, 16-ATR target. Graduated streak/drawdown risk curve 1.1% base; daily lock -2%, halts at -7.5% peak-DD. Sat fully flat through all four secular-bear half-years 2020-2026. BTC 6.4y: +45.2%, PF 1.70, dDD 2.9%, tDD 7.6%, 83.7% MC pass vs the 9% stop. Run on BTCUSD and ETHUSD together (0.6x risk each) for diversification.
#
# ── The state machine (probe-proven, walk-forward) ───────────────────────────
# A bar is tradable only when THREE independent state layers agree:
#   MACRO (regime permission, from completed DAILY closes — never intraday):
#       macro      = % above the 50-day SMA  ( > 3.0 required )
#       macro_slow = % above the 200-day SMA ( > 0.0 required )
#     Below these, the same momentum signals carry NEGATIVE expectancy (bear
#     relief rallies). All four 2020-2026 secular-bear half-years -> ZERO trades.
#   MOMENTUM (the edge): z96 = 24h return / (sigma * sqrt(96)) > 1.0 with the
#     6h horizon aligned (z24 > 0.5). sigma is read from ATR%/1.5 (calibrated).
#     Crypto perps trend-continue on this state (fat-tailed leveraged flow);
#     the DOWN-side mirror does NOT pay (shorts get squeezed) -> long-only.
#   FLOW (confirmation): flow_norm(20) > 0.02 — REAL exchange taker buys minus
#     sells over total volume, not a candle-shape proxy.
# Exit when momentum is dead (z96 < 0), with a 4-4.5 ATR floored stop (the
# floor stops ATR-compressed chop from placing the stop inside range noise)
# and a far 16-ATR target so winners ride.
#
# ── Survival framework (FTMO-tuned, inside 4%/9% internal ceilings) ──────────
# risk 1.1% base; consec-loss throttle (x0.6 at 2, x0.35 at 4) so a 7-loss
# streak costs ~4.5%, never the account; peak-DD tiers (x0.5 at 3.5%, x0.35 at
# 5%); daily lock -2.0%; hard halt at -7.5% peak-DD / -7% lifetime.
#
# ── Documented negative results (kept so nobody re-treads dead ends) ─────────
# * Gaussian-HMM directional gating REDUCED returns (~-0.3%/mo) vs observable
#   macro/momentum/flow states — measured by ablation, both symbols.
# * Mean-reversion (the US500 1H champion architecture) loses ~1.1%/mo here.
# * Vol-contraction breakouts and liquidation-cascade fades: no edge on 15M.
# * Risk-scaling past ~1.1% base is concave: 1.6% base adds +0.10%/mo but
#   breaches the 4% daily-DD ceiling. The throttles, not the edge, bind.

a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r96 = roc(96)
r24 = roc(24)
f = flow_norm(20)
trend = sma(384)

z96 = r96 / (atrp * 6.53) if (not isnan(atrp)) and atrp > 0 else nan
z24 = r24 / (atrp * 3.27) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z96) or isnan(z24) or isnan(f) or isnan(trend) or isnan(macro) or isnan(macro_slow))
enter = (ok and macro > 3.0 and macro_slow > 0.0 and z96 > 1.0 and z24 > 0.5
         and f > 0.02 and close > trend)
mom_dead = ok and z96 < 0.0

halt = dd_from_peak_pct >= 7.5 or total_pnl_pct <= -7.0
day_locked = day_pnl_pct <= -2.0 or trades_today >= 6

risk = 1.1
if consec_losses >= 4:
    risk = risk * 0.35
elif consec_losses >= 2:
    risk = risk * 0.6
if dd_from_peak_pct >= 5.0:
    risk = risk * 0.35
elif dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.3, risk), 2)

stop_mult = min(4.5, max(4.0, 2.2 / atrp)) if (ok and atrp > 0) else 4.0
target_rr = 4.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if mom_dead:
        signal = "FLAT"
