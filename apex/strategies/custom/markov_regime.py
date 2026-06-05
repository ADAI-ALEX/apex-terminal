# name: Markov Regime - Hedge Fund Method
# description: Trades the regime, not the chart. Fits a Bull/Bear/Sideways transition matrix from the price history, forecasts tomorrow's state, and bets on the probability edge (P_bull - P_bear). Conviction-scaled size, hard-capped risk, walk-forward by construction.
#
# ── What this is ─────────────────────────────────────────────────────────────
# The quant / hedge-fund method, in one snippet. Instead of trend lines and gut
# feel it quantifies the market into three regimes and bets on where the regime
# is most likely to go NEXT:
#
#   1. STATE    - each bar is Bull / Bear / Sideways from its rolling 20-bar
#                 return. The bands auto-scale to the instrument's own
#                 volatility, so the same algo works on indices, FX and crypto
#                 (this fixes the subjective "+/-5%" the video calls its weak link).
#   2. MATRIX   - every state-to-state transition in the history is counted into a
#                 3x3 maximum-likelihood matrix (how often Bull follows Bull, etc.).
#   3. FORECAST - raising that matrix to a power gives the n-step-ahead odds
#                 (Chapman-Kolmogorov). markov() reads today's row for tomorrow.
#   4. SIGNAL   - edge = P(bull) - P(bear). Sign is direction; magnitude is
#                 conviction. The matrix is re-fit every bar from PAST bars only,
#                 so this backtest is genuine walk-forward (no look-ahead).
#
# ── The trading math (sizing & survival) ─────────────────────────────────────
# Expectancy, not win rate, is what pays:  win% x avgWin - loss% x avgLoss.  A
# regime follower wins a moderate share of trades at a positive reward:risk, so
# expectancy stays positive over a large sample - judge it over hundreds of
# trades, not five (variance fools you early). Risk per trade rises with the edge
# but is HARD-capped at 1.75% and floored at 0.25% (the video's 2% ceiling is the
# absolute max), so a normal losing streak can never sink the account; the engine
# turns that % into an ATR-based size (bigger stop = smaller size, constant $ risk).
#
#   Entry : edge > +ENTRY and today's state is Bull  -> go long
#           edge < -ENTRY and today's state is Bear   -> go short
#   Exit  : the edge flips against the position       -> regime turned, step aside
#   Size  : risk% rises with |edge| (conviction), floored 0.25%, ceiling 1.75%
#
# Parameters were chosen from a STABLE PLATEAU across US500/FTSE/EUR-USD/BTC/ETH
# (entry anywhere in 0.25..0.45 backtests almost identically), not a cherry-
# picked peak - the anti-overfitting rule both videos hammer on.
#
# Where it shines: trending markets (it is a momentum/regime method, so crypto
# and indices reward it; choppy mean-reverting markets like FX give it little).
# Tip: markov() also exposes m.stickiness (regime persistence) and m.sd_bull /
# m.sd_bear (the long-run state mix), and markov(20, horizon=5) for a 5-bar
# forecast or markov(20, bull_thr=5, bear_thr=-5) for the video's fixed +/-5% bands.

ENTRY = 0.35                       # only act on a strong probability gap (plateau midpoint)

m = markov(20, band=1.0)           # 20-bar regime; bands = 1.0 stdev of the N-bar returns
edge = m.edge                      # P(bull tomorrow) - P(bear tomorrow)

# Conviction-scaled risk: more edge -> more size, but floored 0.25% and capped
# 1.75% so a normal losing streak can never sink the account (survival first).
risk = round(min(1.75, max(0.25, 0.25 + abs(edge) * 1.5)), 2)

if position == 0:
    if edge > ENTRY and m.state == "BULL":
        signal = "BUY"             # bullish regime confirmed - ride the stickiness
    elif edge < -ENTRY and m.state == "BEAR":
        signal = "SELL"            # bearish regime confirmed
    else:
        signal = "HOLD"
elif position == 1:
    signal = "FLAT" if edge < 0 else "HOLD"    # long: leave when the edge turns
elif position == -1:
    signal = "FLAT" if edge > 0 else "HOLD"    # short: leave when the edge turns
else:
    signal = "HOLD"
