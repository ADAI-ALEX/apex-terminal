# name: Global Macro V4 (BTC leg + Challenge Mode)
# description: Phase-5.4 master — the BTC 4H leg of the validated cross-sector account allocation, now with a CHALLENGE_MODE switch. False (default, institutional): the V2/V3 gate set (z24h>0.9, flow>0.015) — 1.48%/mo PF 5.25 MC 95.7% standalone. True (funding-challenge): gates move to the OTHER measured corner of the Phase-5.2 stability plateau (z24h>0.8, flow>0.01, day cap 6) — +44% trade frequency (36->52 over 6.4y), no losing half-year window, worst dDD 3.78/tDD 4.93, at ~0.1%/mo windowed yield cost. Both corners were walk-forward validated BEFORE this switch existed; it toggles between proven configurations, never into unvalidated space. DEPLOY: this file on BTCUSD 240m + Auction Flow V5.1 (Hybrid) on US500 60m — the two-pillar blend remains the frontier: 2.27%/mo all-climate, +3.4..+4.5%/mo in 5/7 fresh windows, worst dDD 3.70 / tDD 8.30 (see crypto_v3_master / dev_crypto_v3.py).
#
# ── Phase-5.4 verdicts (measured in scripts/dev_crypto_v3.py — do not re-tread)
# * THIRD PILLAR (GOLD) REJECTED. The clean-data daily turtle (momentum_trend,
#   XAUUSD D1, points costs) is real but LUMPY alpha: in 13 fresh half-year
#   windows it trades 1-3 times for a mean +0.09%/mo standalone (one big
#   window, 2025H2 +2.20%/mo; four negative). Blended (AVG battery): mean
#   +0.32%/mo BUT total DD breaches the 9% limit at 9.59% in 2025H1 — gold's
#   drawdown windows overlap the blend's weakest stretch instead of filling
#   it. Trimmed to fit the buffer its contribution is negligible. ALSO: daily
#   equity marking cannot resolve an intraday daily-DD contribution (a 1.5%
#   daily-stop position can print ~1.9% inside one day, invisible at D1) —
#   the leg cannot satisfy a hard daily-DD guarantee at this data resolution.
#   A third pillar must be anti-correlated in DRAWDOWN WINDOWS, not merely a
#   different asset class (same lesson as ETH in Phase 5.3).
# * DYNAMIC CAPITAL ROTATION REJECTED (empirically, not just structurally).
#   Structurally: books are per-instrument snippets — no cross-asset state.
#   The long-only macro gate already implements passive rotation (BTC flat =
#   zero runway consumed; live account-level breakers couple the legs).
#   Empirically: in 2025H1 (the tDD-critical window) BTC was NOT flat (6
#   trades), so rotating risk away from it was unavailable; in 2026 (BTC
#   flat) the US500 leg was NEGATIVE — rotating BTC's idle risk into it
#   would have amplified the only losing window. Rotation helps exactly
#   nowhere in this history.
# * Cost profiles are per asset class everywhere: crypto = % of notional
#   (0.12 RT), index/metals = points (US500 0.5, XAUUSD 0.4).
#
# ── CHALLENGE_MODE guidance ──────────────────────────────────────────────────
# True only while inside a prop-firm evaluation window, where hitting the
# profit target inside the time box is worth a thinner per-trade edge. Flip
# to False the day the account is funded. The US500 leg ships unchanged in
# both modes (its V5.1 sizing is already the validated envelope).

CHALLENGE_MODE = False

a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r6 = roc(6)
r18 = roc(18)
f = flow_norm(20)
trend = sma(24)

z24 = r6 / (atrp * 1.8) if (not isnan(atrp)) and atrp > 0 else nan
z3d = r18 / (atrp * 3.12) if (not isnan(atrp)) and atrp > 0 else nan

z_min = 0.8 if CHALLENGE_MODE else 0.9
f_min = 0.01 if CHALLENGE_MODE else 0.015
day_cap = 6 if CHALLENGE_MODE else 4

ok = not (isnan(z24) or isnan(z3d) or isnan(f) or isnan(trend) or isnan(macro) or isnan(macro_slow))
enter = (ok and macro > 3.0 and macro_slow > 0.0 and z24 > z_min and z3d > 0.5
         and f > f_min and close > trend)
mom_dead = ok and z3d < 0.0

halt = dd_from_peak_pct >= 7.5 or total_pnl_pct <= -7.0
day_locked = day_pnl_pct <= -2.0 or trades_today >= day_cap

risk = 2.8
if consec_losses >= 4:
    risk = risk * 0.35
elif consec_losses >= 2:
    risk = risk * 0.6
if dd_from_peak_pct >= 6.0:
    risk = risk * 0.4
elif dd_from_peak_pct >= 4.5:
    risk = risk * 0.6
risk = round(max(0.3, risk), 2)

stop_mult = min(5.0, max(4.0, 2.2 / atrp)) if (ok and atrp > 0) else 4.0
target_rr = 6.0

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
