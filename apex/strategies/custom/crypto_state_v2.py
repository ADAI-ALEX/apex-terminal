# name: Crypto State V2 (BTC 4H)
# description: Phase-5.2 crypto perpetual state engine — V1's probe-proven LONG-ONLY dual-momentum stack moved UP the timeframe ladder to the 4-HOUR chart. Same three state layers must agree: (1) MACRO permission — price >3% above the 50-day daily SMA AND above the 200-day (sat flat through every 2020-2026 secular-bear half-year); (2) MOMENTUM ignition — vol-normalized 24h z>0.9 with 3-day alignment z>0.5 (divisors re-calibrated for 4H: atrp/sigma ratio 1.36 vs 1.5 on 15M); (3) FLOW confirmation — real taker-buy imbalance >1.5%. Exits on 3-day momentum death; 4-5 ATR disaster stop (never touched in 17 months of 1-minute replay); 6R target. Risk 2.8% base — the 4H DD footprint is ~half of 15M per unit of yield, which is what lets sizing rise toward the 4% daily ceiling (loosened throttle tiers x0.6@4.5% / x0.4@6%, validated +0.19%/mo at no DD cost). BTC 6.4y walk-forward: +113.8% (1.48%/mo, 2.5x V1), PF 5.25, 66.7% win, dDD 3.78%, tDD 5.60%, MC 95.7% vs the -9% stop, equity R^2 0.94. Run on BTCUSD at 240m ONLY (ETH does not replicate above 15M — documented).
#
# ── Why 4H beats 15M (Phase-5.2 campaign, scripts/dev_crypto_v2.py) ──────────
# The edge per unit TIME is roughly constant across timeframes (~0.55%/mo at
# V1 sizing on 15M, 1H and 4H) — but the DD footprint is not. Fewer, larger,
# higher-conviction trades concentrate the same edge into a 66.7%-win PF>5
# stream whose worst total DD is 5.6% instead of 7.6%, so base risk can rise
# from 1.1% to 2.8% (sizing on 1H/15M is concave: the throttles bind first).
# Costs become noise: stressing 0.12% -> 0.18% RT moves the 6.4y result by
# only -0.02%/mo (the 15M engine lived on a cost knife-edge).
#
# ── The state machine (probe-proven, walk-forward, re-calibrated for 4H) ─────
#   MACRO (regime permission, from completed DAILY closes — never intraday):
#       macro      = % above the 50-day SMA  ( > 3.0 required )
#       macro_slow = % above the 200-day SMA ( > 0.0 required )
#   MOMENTUM: z24h = roc(6)/(atrp*1.80) > 0.9 and z3d = roc(18)/(atrp*3.12)
#     > 0.5 (probe 2026-06: median atrp/sigma = 1.36 on 4H; divisor =
#     sqrt(N)/1.36). Gates sit at the CENTER of a verified stability plateau
#     (z in [0.8,1.0] x flow in [0.01,0.02] all profitable, no losing
#     half-year window anywhere on the plateau).
#   FLOW: flow_norm(20) > 0.015 — REAL taker buys minus sells over volume.
#   LOCAL TIMING: close > sma(24) (the 4-day trend in 4H bars).
# Exit when the 3-DAY momentum is dead (z3d < 0) — at 4H resolution the 24h
# z is too twitchy to exit on (that is V1's premature-exit failure the
# mandate identified). Stop 4 ATR (~5% of price) is disaster-only.
#
# ── Survival framework (FTMO-tuned, inside 4%/9% internal ceilings) ──────────
# risk 2.8% base; consec-loss throttle (x0.6 at 2, x0.35 at 4); LOOSENED
# peak-DD tiers (x0.6 at 4.5%, x0.4 at 6.0%) — on 4H the loosening adds
# +0.19%/mo at zero DD cost (tDD 5.43 -> 5.60), unlike 15M where the V1
# tiers were load-bearing; daily lock -2.0%; halt -7.5% peak-DD / -7% total.
#
# ── Documented negative results (Phase-5.2 — do not re-tread) ────────────────
# * Wide ATR trailing exits (6/8/10 ATR swept) LOSE to the momentum-death
#   exit on BOTH 1H and 4H — crypto retraces through any affordable trail
#   before trends resume. The mandate's trailing-stop lever is dead.
# * Turtle/Donchian 20-day breakout entries (even macro-gated): 0.29%/mo —
#   breakouts buy chop tops; the z-ignition entry is strictly better.
# * ETHUSD does NOT replicate above 15M (0.2%/mo on 1H and 4H, gates barely
#   fire). V2 is BTC-only; diversify with US500 V5.2, not a second symbol.
# * 1H sizing is concave: base 2.2% -> 0.84%/mo with tDD already 6.7%. The
#   4H engine dominates the whole 1H risk frontier.
# * >3%/mo all-climate remains unreachable at real costs at these ceilings:
#   bull half-years print +2.2..+4.4%/mo, bear halves are (correctly) flat.
#   1.48%/mo with MC 95.7% is the honest frontier; anything above it on this
#   stack was bought with daily-DD breaches (4.30% at base 3.2%).
#
# ── Execution fidelity (1-minute replay, 2025-01..2026-05) ───────────────────
# All 9 trades in the 1M coverage window exited at the 4H close (momentum
# death); zero stop/target intrabar fills -> 1M-replay return delta 0.000%.
# Worst 1M intratrade adverse excursion 0.70R ~= 1.95% equity at base risk.

a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r6 = roc(6)
r18 = roc(18)
f = flow_norm(20)
trend = sma(24)

z24 = r6 / (atrp * 1.8) if (not isnan(atrp)) and atrp > 0 else nan
z3d = r18 / (atrp * 3.12) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z24) or isnan(z3d) or isnan(f) or isnan(trend) or isnan(macro) or isnan(macro_slow))
enter = (ok and macro > 3.0 and macro_slow > 0.0 and z24 > 0.9 and z3d > 0.5
         and f > 0.015 and close > trend)
mom_dead = ok and z3d < 0.0

halt = dd_from_peak_pct >= 7.5 or total_pnl_pct <= -7.0
day_locked = day_pnl_pct <= -2.0 or trades_today >= 4

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
