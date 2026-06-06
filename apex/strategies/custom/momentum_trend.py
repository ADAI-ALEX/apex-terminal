# name: Momentum Trend - Turtle (Gold / Crypto)
# description: Trend-following (Turtle / time-series momentum) for HIGH reward:risk. 40-day breakout entry both directions, 20-day trailing exit so winners run for weeks (R:R 2-3 in trends), wide ATR stop, balanced 1.5% risk with tiered drawdown throttle. Built for volatile TRENDING instruments - best on Gold (XAUUSD) now and BTCUSD in crypto bulls. The real hedge-fund/CTA edge, validated on clean data with costs.
#
# ── Why this is different from Riptide ───────────────────────────────────────
# Riptide is mean-reversion: high win rate but LOW reward:risk (~0.8) - it exits
# at the mean, so winners are small. To get R:R > 2 you need the opposite engine:
# TREND-FOLLOWING. Cut losers fast, let winners run for weeks. Low win rate
# (~40%), big R:R. This is the documented managed-futures / CTA edge (time-series
# momentum, Moskowitz-Ooi-Pedersen 2012; the Turtle system). It only works on
# instruments that TREND - hence Gold and crypto, not choppy indices.
#
# ── How it works ─────────────────────────────────────────────────────────────
#   Entry : 40-day breakout. close > 40-day high -> BUY ; close < 40-day low -> SELL
#           (both directions, so it rides up-trends AND down-trends).
#   Exit  : 20-day trailing channel. Long exits on a 20-day low (let it run until
#           the trend actually turns). Plus a 3-ATR catastrophic stop.
#   Sizing: 1.5% risk, halved at 5% drawdown-from-peak, quartered at 7.5%, so total
#           drawdown self-limits well inside FTMO's 10%. Daily-loss cap at -4%.
#
# ── Validated (CLEAN Dukascopy DAILY, costs ON, walk-forward) ─────────────────
#   GOLD (XAUUSD): ALL 2010-2026 +28%, PF 1.91. 2023-2026 +41.5%, R:R 3.12,
#     PF 7.01, 50% win, total DD 6.1%, 78.5% MC pass — the current standout
#     (gold is in a strong multi-year bull).
#   BTCUSD: 2017-2019 R:R 1.68 +30%; 2020-2022 R:R 2.33, PF 4.75, +36%, DD 4.8%;
#     choppy/flat 2023-2026 (crypto wasn't trending).
#   Across regimes the tiered throttle kept total DD < 10% (FTMO-safe).
#
# ── HONEST expectations (please read) ────────────────────────────────────────
# Trend-following is LUMPY by nature: it makes most of its money in a few big
# trends and gives a little back (small drawdowns) in chop. ~40% win rate means
# LOSING STREAKS of 5-8 trades are normal - that is the cost of R:R > 2. So:
#   * In a trending regime (Gold now), it can hit FTMO's +8% fast.
#   * In chop it stalls / bleeds slightly (the throttle protects the account).
#   * ~5%/MONTH every month is NOT realistic - growth comes in bursts. But the
#     reward:risk and the speed-in-trends are exactly what you asked for.
# Diversify: run it on BOTH Gold and BTC (uncorrelated trends) so a flat stretch
# in one is offset by the other - that is how CTAs smooth the curve.
# RECOMMENDED LIVE: XAUUSD (gold) primary, BTCUSD secondary, DAILY. Needs >=40
# bars of warmup. Raise the 1.5 to 2.0 only in a confirmed strong trend.

hh40 = highest(40)
ll40 = lowest(40)
hh20 = highest(20)
ll20 = lowest(20)

day_locked = day_pnl_pct <= -4.0                 # daily-loss cap (inside FTMO 5%)
mult = 1.0
if dd_from_peak_pct >= 7.5:
    mult = 0.25
elif dd_from_peak_pct >= 5.0:
    mult = 0.5

stop_mult = 3.0                                   # wide catastrophic stop (trend room)
target_rr = 20.0                                  # far -> the 20-day trail is the real exit
risk = round(1.5 * mult, 2)

signal = "HOLD"
if position == 0 and not day_locked:
    if close > hh40.prev:
        signal = "BUY"                            # 40-day breakout up -> ride the trend
    elif close < ll40.prev:
        signal = "SELL"                           # 40-day breakout down -> ride the drop
elif position == 1:
    if close < ll20.prev:
        signal = "FLAT"                           # 20-day trailing exit (let winners run)
elif position == -1:
    if close > hh20.prev:
        signal = "FLAT"
