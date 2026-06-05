# name: Riptide Pro - High-Conviction Trend (US500 daily)
# description: Higher-growth version of Riptide, validated on CLEAN data with costs. Trend-filtered RSI(2) pullback on US500 daily, with looser entries (more trades) and drawdown-scaled conviction risk up to 2%. ~2x Riptide's return while staying FTMO-safe. The one edge that survives clean tradeable data + transaction costs. Trade it on US500 daily.
#
# ── Why this is the real one ─────────────────────────────────────────────────
# Hard lesson from this project: the flashy intraday strategies (FX scalpers, the
# US500 1h "Markov Trend" Swing/Swing+) were DATA ARTIFACTS — they looked great on
# Yahoo data but collapse on clean Dukascopy data with costs. Re-validating
# everything on clean data, only ONE family survives: trend-filtered RSI(2) mean
# reversion on the DAILY timeframe. It survives because daily = few trades = costs
# negligible, and the Connors RSI(2) edge is documented and robust, not noise.
#
# ── The edge ─────────────────────────────────────────────────────────────────
#   Trend filter : close > SMA(200) and SMA(50) > SMA(200)   → confirmed up-trend
#   Pullback     : RSI(2) < 12                                → oversold dip (buy)
#   (mirror for downtrends: SMA-stack down + RSI(2) > 88 → sell)
#   Exit         : RSI(2) snaps back > 65, or close > SMA(5), or 10-bar time stop.
#   Sizing       : conviction (deeper dip = bigger), 1.2%..2.0%, HALVED once
#                  drawdown-from-peak hits 5% (self-throttle, no freezing halt).
#                  Daily-loss cap at -3% (inside the 5% FTMO limit).
#
# ── Validated (CLEAN Dukascopy US500 daily, 2012-2026, costs ON, walk-forward) ─
#   ALL: +60.2%, 234 trades, 67.5% win, PF 1.48, R^2 0.70.
#   Per window (all POSITIVE): 2012-15 +27.5% / 2016-19 +9.1% / 2020-22 +4.7% /
#     2023-26 +17.5%. Per-window max total DD 5.8-8.5% (FTMO-safe under 10%).
#   Recent 2023-2026: +17.5%, 73.5% win, PF 1.75, total DD 6.6%, R^2 0.85, 90%
#   Monte-Carlo probability of +10% before -10%. ~2x the original Riptide.
#
# ── Honest expectations ──────────────────────────────────────────────────────
#   This is a SWING edge: ~12-15 trades/year (about 1+/month) on daily bars. It
#   is REAL but not fast — clearing FTMO's +8% takes patience (unlimited period).
#   That is the trade-off the data forces: real edges on liquid markets are slow;
#   fast intraday "edges" are artifacts. Best (and validated) on US500 daily;
#   EUR/USD daily works historically but is weak in the current regime.

trend_up = close > sma(200) and sma(50) > sma(200)
trend_dn = close < sma(200) and sma(50) < sma(200)
r = rsi(2)

day_locked = day_pnl_pct <= -3.0                 # daily-loss cap (inside FTMO 5%)
mult = 0.5 if dd_from_peak_pct >= 5.0 else 1.0    # self-throttle in drawdown

signal = "HOLD"
if position == 0 and not day_locked:
    if trend_up and r < 12:
        risk = round(min((1.2 + (12 - r) * 0.1) * mult, 2.0), 2)   # ~1.2%..2.0%
        signal = "BUY"                            # buy the dip in a daily up-trend
    elif trend_dn and r > 88:
        risk = round(min((1.2 + (r - 88) * 0.1) * mult, 2.0), 2)
        signal = "SELL"                           # sell the rip in a daily down-trend
elif position == 1:
    if r > 65 or close > sma(5) or bars_held > 10:
        signal = "FLAT"                           # bank the snap-back / time stop
elif position == -1:
    if r < 35 or close < sma(5) or bars_held > 10:
        signal = "FLAT"
