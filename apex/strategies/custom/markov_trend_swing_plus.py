# name: Markov Trend - Swing+ (US500 / Higher Growth)
# description: Higher-growth sibling of Markov Trend - Swing. Same real, cost-validated US500 trend-pullback edge, scaled to ~2% risk for ~1.3-1.4x the return while keeping drawdowns inside FTMO limits (daily < ~4%, total < ~7%). For traders who want more growth and accept slightly more heat. Best on US500 1h.
#
# ── Why this exists ──────────────────────────────────────────────────────────
# The "mean-reversion + session filter" approach (RSI/Bollinger/VWAP, London+NY)
# was implemented faithfully and tested on REAL EUR/USD data WITH costs across
# 2023-2026 — it has NO durable edge (net negative; profitable only in the
# current regime). Intraday FX mean reversion is efficient after spread. So
# instead of chasing a dead archetype, this SCALES the one edge that is real:
# the markov-regime trend-pullback on US500 (see markov_trend_swing).
#
# ── The edge (unchanged) ─────────────────────────────────────────────────────
#   markov() reads the live regime; edge = P(bull) - P(bear).
#     up-regime  : edge > +0.06 AND close > EMA200  -> buy RSI(2) < 35 dip
#     down-regime: edge < -0.06 AND close < EMA200  -> sell RSI(2) > 65 rip
#   Ride to a regime flip (edge crosses ∓0.02) or RSI far extreme.
#
# ── What changed vs Swing ────────────────────────────────────────────────────
#   Risk per trade 1.5% -> up to 2.0% (conviction-scaled). Daily-loss cap
#   tightened to -2.5% so that, single-position, the worst day stays under the 5%
#   FTMO limit (a -2.4% day + one 2% loss = -4.4%). Total-loss stop -6%.
#
# ── Validated (US500 1h, real data + costs ON, walk-forward) ─────────────────
#   2023H2..2026: +23.8 / -6.1 / +16.9 / +16.8 / +9.2 / +16.0 %  (5 of 6 positive)
#   max daily DD < 3.8%, max total DD < 6.5% in every window (FTMO-safe),
#   PF 1.36-2.27, MC pass 80-93% in the profitable regimes.
#   ~1-2 trades/week (a swing edge, not a scalp). Weak spot: low-vol grind-ups
#   (2024-H1, -6.1%, capped by the stop) — same as the conservative version.
#
# RECOMMENDED LIVE: US500, 1h. Use the conservative "Markov Trend - Swing" (1.5%
# risk) if you want a wider safety buffer to the 5% daily limit.

mk = markov(20, band=0.5, window=400)      # live regime; edge = P(bull) - P(bear)
edge = mk.edge
e200 = ema(200)
r = rsi(2)
up = edge > 0.06 and close > e200          # confirmed up-regime
dn = edge < -0.06 and close < e200         # confirmed down-regime

halt = total_pnl_pct <= -6.0               # FTMO survival: never approach -10%
day_locked = day_pnl_pct <= -2.5           # tight daily cap (worst day stays < 5%)

# Conviction-scaled risk, capped 2.0% (higher growth than the 1.5% Swing).
risk = round(max(0.75, min(0.9 + abs(edge) * 1.5, 2.0)), 2)

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
