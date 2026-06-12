# name: Crypto V3 Master (BTC 4H + US500 Ensemble)
# description: Phase-5.3 MASTER ALLOCATION — the account-level ensemble that broke the frequency/yield wall the single crypto book could not: run THIS file on BTCUSD 240m (signal stack identical to Crypto State V2 — the proven 4H macro-gated momentum engine) ALONGSIDE Auction Flow V5.1 (Hybrid) on US500 1H. Cross-sector blending is the ONLY validated path past V2's 1.48%/mo: crypto and equity-index drawdowns run on different clocks, so the blend lifts frequency ~9x (≈4.7 trades/mo) and prints +3.4 to +4.5%/mo in 5 of 7 fresh half-year windows (2023-2026) while every window respects the prop limits: worst daily DD 3.70% (<4.0), worst total DD 8.30% (<9.0). All-climate ensemble-period mean 2.27%/mo; 6.4y blended +164% (2.14%/mo, MC 89.5% vs -9%). Validated portfolio-level in scripts/dev_crypto_v3.py (full-resolution equity merge, costs ON per instrument class).
#
# ── THE ALLOCATION (deploy exactly this; sizing is inside each file) ──────────
#   leg 1: crypto_v3_master.py (this file)      -> BTCUSD  240m  (2.8% base)
#   leg 2: auction_flow_v5_1_hybrid.py          -> US500    60m  (1.2-1.9% band)
# Live, the per-book breakers (day_pnl_pct / dd_from_peak_pct / total_pnl_pct)
# read ACCOUNT-level equity, so the books throttle each other automatically —
# the backtest measured them per-book, which is the looser assumption; live
# coupling only tightens it.
#
# ── Phase-5.3 negative results (measured, do NOT re-tread) ───────────────────
# * Intraday sub-state harvesting under the macro gate (vector 1): DEAD. A
#   macro-gated RSI(2) dip-buy with flow filter on 15M loses on BOTH symbols
#   (BTC PF 0.68, ETH PF 0.88, costs on) — crypto mean reversion does not pay
#   at ANY tested granularity, even inside the bull regime.
# * Same-sector frequency stacking: V2(BTC4H)+V1(BTC15M)+V1(ETH15M) looked
#   like 2.40%/mo on the full path but FAILED fresh-window stress — all three
#   long-only crypto books co-crash from a standing start: worst daily DD
#   6.09%, worst total DD 13.02%. Uniform downscale to compliance returns
#   ~1.4%/mo — no better than V2 alone. The full-run number was path-flattered
#   by accumulated-profit throttle states; fresh windows are how challenges
#   actually start. ALWAYS stress ensembles on fresh windows.
# * ETHUSD adds nothing at portfolio level: +0.33%/mo for ~3.5pts of worst-
#   window total DD (coincident with BTC). Cannot be risk-scaled either — at
#   1.6% base its own internal halt kills the book mid-history.
# * US500 leg at V5.2 sizing (1.5-2.3%): blend breaches total DD (9.43% in
#   2025H1). V5.1 sizing (1.2-1.9%) restores the buffer (8.30%) for ~0.25%/mo.
# * COST-MODEL TRAP: charge crypto perps percent-of-notional (0.12% RT) and
#   index CFDs fixed POINTS (~0.5pt US500). Applying the crypto cost model to
#   US500 is a ~14x overcharge that falsely kills the scalper leg.
# * >5%/mo all-climate remains out of reach honestly; >3%/mo is real but only
#   in normal/bull climates. 2026-to-date is the ensemble's one losing stretch
#   (-0.67%/mo: index leg soft, BTC correctly flat below its macro gate).
#
# ── The BTC leg below = Crypto State V2 verbatim (see that file's header for
#    the full 4H derivation: z-divisor calibration, gate plateau, 1M-replay
#    fidelity, V2-vs-V1 benchmarks). Kept byte-identical so the two files
#    cannot drift; retire one name if both confuse the strategy list. ─────────

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
