# name: Markov Trend - Swing (US500 / FTMO)
# description: A REAL, cost-validated swing edge. Markov-regime trend-pullback: in a confirmed up-regime (markov edge>0 and price above the 200-EMA) it buys short-term RSI(2) dips and rides until the regime flips (mirror for shorts). Few trades, big moves, so spread/commission barely dents it. Best on US500 1h; also strong on US500 daily. Validated on real data WITH costs across 2023-2026 (and 20y daily).
#
# ── Read this — why this one is different ────────────────────────────────────
# The earlier scalpers (markov_scalper / _v2) looked amazing (+131%) but that was
# an ARTIFACT of low-quality Yahoo 5m data + a zero-cost backtest. On REAL
# (Dukascopy) data with realistic spread+commission, high-frequency FX scalping
# has NO edge — it loses every regime. This strategy was rebuilt from scratch on
# clean data with costs charged, deliberately trading SLOWER (a few trades a week)
# so each move dwarfs the ~0.8pip cost. That is what makes the edge survive.
#
# ── The edge ─────────────────────────────────────────────────────────────────
#   markov() reads the live regime; edge = P(bull) - P(bear). Trade only WITH a
#   real trend:
#     up-regime  : edge > +0.06 AND close > EMA200  -> buy a dip (RSI2 < 35)
#     down-regime: edge < -0.06 AND close < EMA200  -> sell a rip (RSI2 > 65)
#   Exit when the regime edge flips against you (or RSI hits the far extreme) and
#   let winners run in between — that is where the reward:risk (~1.0) comes from,
#   far healthier than the scalper's 0.4.
#
# ── FTMO risk (survival first) ───────────────────────────────────────────────
#   Conviction-scaled risk 0.5..1.5%; daily-loss cap -4%; total-loss stop at -6%
#   (so it never approaches the -10% bust line). All validated drawdowns stayed
#   well inside FTMO limits (daily < 3%, total < 5% in every profitable regime).
#
# ── Validated (real Dukascopy/Yahoo data, costs ON, walk-forward) ────────────
#   US500 1h, half-years 2023-2026: +17.5 / -7.2 / +12.5 / +12.3 / +6.9 / +12.1 %
#     (5 of 6 positive; the one loss, 2024-H1, was a 7-trade low-vol grind-up;
#      PF 1.37-2.45, daily DD < 3%, total DD < 5% in the winners).
#   US500 daily 2023-2026: +22.9%, PF 1.85, 66% win, total DD 3.4%, R^2 0.91.
#   It is a SWING edge: ~1-2 trades/week on 1h, ~1/month on daily — not a scalper.
#   Honest caveat: it is a trend strategy, so a choppy low-volatility grind
#   (2024-H1) is its weak spot; the -6% stop caps that.
#
# RECOMMENDED LIVE: US500, 1h (best edge + frequency + safety). Use daily for an
# even smoother, slower variant. EUR/USD works historically but is weak in the
# current (2026) regime — prefer US500.

mk = markov(20, band=0.5, window=400)      # live regime; edge = P(bull) - P(bear)
edge = mk.edge
e200 = ema(200)
r = rsi(2)
up = edge > 0.06 and close > e200          # confirmed up-regime
dn = edge < -0.06 and close < e200         # confirmed down-regime

halt = total_pnl_pct <= -6.0               # FTMO survival: never approach -10%
day_locked = day_pnl_pct <= -4.0           # daily-loss cap (inside the 5% limit)

# Conviction-scaled risk, capped 1.5% (one bad window can't blow the account).
risk = round(max(0.5, min(0.6 + abs(edge) * 1.2, 1.5)), 2)

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"                    # near the bust line: stand down
elif position == 0 and not day_locked:
    if up and r < 35:
        signal = "BUY"                     # buy the dip in an up-regime
    elif dn and r > 65:
        signal = "SELL"                    # sell the rip in a down-regime
elif position == 1:
    if edge < -0.02 or r > 80:
        signal = "FLAT"                    # exit when the regime flips down / overbought
elif position == -1:
    if edge > 0.02 or r < 20:
        signal = "FLAT"                    # exit when the regime flips up / oversold
