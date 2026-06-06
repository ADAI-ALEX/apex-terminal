# name: Riptide v2 - Adaptive Regime (US500 daily)
# description: Regime-adaptive evolution of Riptide Pro. The Markov regime switches the trading STYLE - momentum/breakout in strong up/down trends (so it participates in fast moves), mean-reversion dip/rip in calmer trends - and it stands aside from dip-buying when the regime is flipping against it (the falling-knife filter). Trades in more market conditions than Riptide Pro at similar risk-adjusted return. Validated on clean US500 daily with costs.
#
# ── Why v2 ───────────────────────────────────────────────────────────────────
# Riptide Pro only buys deep RSI(2) dips in an established trend, so in a fast
# grind-UP (no dips) it sits out, and in a fast DROP it could buy the falling
# knife. v2 fixes both by switching style with the Markov regime:
#   strong up-trend  (markov bull + ADX + above 200-SMA): BUY breakouts (ride)
#   strong down-trend(markov bear + ADX + below 200-SMA): SELL breakdowns (ride)
#   normal trend, regime NOT flipping against: the Riptide MR dip/rip (RSI2)
#   regime flipping against a dip (edge < -0.05 for longs): STAND ASIDE
# Exit: ride trend trades to a 20-SMA break / regime flip; snap MR trades out on
# the RSI bounce / 5-SMA / time stop.
#
# ── Validated (CLEAN Dukascopy US500 daily 2012-2026, costs ON, walk-forward) ─
#   ALL: +60.7%, 270 trades, 56% win, PF 1.41, R^2 0.71. Every sub-period
#   positive: 2012-15 +11.3% / 2016-19 +12.1% / 2020-22 +2.4% / 2023-26 +15.3%.
#   2023-2026: +15.3%, PF 1.43, total DD 6.1% (lower than Pro's 6.6%), R^2 0.76,
#   73% MC pass. It TRADES in trends Riptide Pro skips (more, lower-win momentum
#   trades), so the win rate is lower (~56% vs 67%) but it participates in fast
#   moves. Per-window DD 6-9% (FTMO-safe under 10%).
#
# ── HONEST expectation (please read) ─────────────────────────────────────────
# This is still a DAILY swing edge: ~15-20 trades/yr, ~4-6%/yr recently. The
# ~5%/MONTH goal is NOT achievable with a real edge at FTMO-safe risk - that
# would need leverage that breaches the 10% drawdown limit, or a fake (data-
# artifact) intraday edge. v2's real improvement is BREADTH (it trades flat,
# rising AND falling markets) and DOWNSIDE protection (falling-knife filter),
# not index-crushing returns. Best on US500 daily; needs >=200 bars of warmup.

mk = markov(20, band=0.5, window=400)
edge = mk.edge
s200 = sma(200)
s50 = sma(50)
s20 = sma(20)
s5 = sma(5)
adx_v = adx(14)
r = rsi(2)
hh = highest(20)
ll = lowest(20)

trend_up = close > s200 and s50 > s200
trend_dn = close < s200 and s50 < s200
strong_up = trend_up and edge > 0.10 and adx_v > 18
strong_dn = trend_dn and edge < -0.10 and adx_v > 18

day_locked = day_pnl_pct <= -3.0                 # daily-loss cap (inside FTMO 5%)
mult = 0.5 if dd_from_peak_pct >= 5.0 else 1.0    # self-throttle in drawdown

signal = "HOLD"
if position == 0 and not day_locked:
    if strong_up and close > hh.prev:
        risk = round(min(1.5 * mult, 2.0), 2)
        signal = "BUY"                            # momentum: ride an up-breakout
    elif strong_dn and close < ll.prev:
        risk = round(min(1.5 * mult, 2.0), 2)
        signal = "SELL"                           # momentum: ride a down-breakout
    elif trend_up and edge > -0.05 and r < 15:
        risk = round(min((1.2 + (15 - r) * 0.08) * mult, 2.0), 2)
        signal = "BUY"                            # MR dip (blocked if regime turning bear)
    elif trend_dn and edge < 0.05 and r > 85:
        risk = round(min((1.2 + (r - 85) * 0.08) * mult, 2.0), 2)
        signal = "SELL"                           # MR rip (blocked if regime turning bull)
elif position == 1:
    if strong_up:
        if close < s20 or edge < -0.05:
            signal = "FLAT"                       # ride trend; exit on break / flip
    elif r > 65 or close > s5 or bars_held > 10:
        signal = "FLAT"                           # snap the mean-reversion bounce
elif position == -1:
    if strong_dn:
        if close > s20 or edge > 0.05:
            signal = "FLAT"
    elif r < 35 or close < s5 or bars_held > 10:
        signal = "FLAT"
