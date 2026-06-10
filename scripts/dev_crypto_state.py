"""Dev-only iterative harness for the Phase-5 crypto state engine.

Runs candidate snippets over the DEEP Binance perp seeds (BTCUSD/ETHUSD,
2020-2026) through the production backtest engine with percentage costs ON
(0.12% notional round trip ~= taker fee + slippage on a perp, or an FTMO crypto
CFD spread). Reports per-climate-window: trades, win%, PF, return, return/month,
daily/total floating drawdown, equity linearity R^2 and the Monte-Carlo pass
probability of +10% before -9% (the internal hard stop).

Window sets:
  dev   — 4 contrasting half-years (fast iteration, ~90s/candidate)
  full  — all 13 half-year climates 2020-2026 (validation)
  one   — single compounding 6.4-year run (true total-DD accounting)
  eth   — cross-asset check on ETHUSD

Run:  venv/Scripts/python.exe scripts/dev_crypto_state.py <ver> [dev|full|one|eth|eth5|btc5|btc60] [cost_pct]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

logger.remove()

from apex.backtest import dataset  # noqa: E402
from apex.backtest.engine import run_backtest  # noqa: E402
from apex.backtest.runner import LOCAL_BACKTEST_MARKETS  # noqa: E402
from apex.config import MARKETS, get_settings  # noqa: E402

#: Round-trip transaction cost as % of notional (taker+slip both sides). The
#: stress runs use 1.5x this to prove the edge is not a cost-knife-edge artifact.
COST_PCT = 0.12

_CACHE: dict = {}


def full_series(key: str, tf: str):
    if (key, tf) not in _CACHE:
        _CACHE[(key, tf)] = dataset.load(key, 0, timeframe=tf)
    return _CACHE[(key, tf)]


def _slice(series, start, end):
    cs = series.candles
    idx = [i for i, c in enumerate(cs)
           if (start is None or c.time.isoformat()[:10] >= start)
           and (end is None or c.time.isoformat()[:10] < end)]
    if not idx:
        return [], {}
    a, b = idx[0], idx[-1] + 1
    return cs[a:b], {n: v[a:b] for n, v in series.exo.items()}


def linearity(eq: list[dict]) -> float:
    n = len(eq)
    if n < 3:
        return 0.0
    xs = list(range(n))
    ys = [p["equity"] for p in eq]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return round((sxy * sxy) / (sxx * syy), 3)


def run(code: str, key: str, tf_min: int, start=None, end=None, cost_pct=COST_PCT) -> dict:
    tf = dataset.suffix_for(tf_min)
    s = full_series(key, tf)
    cs, exo = _slice(s, start, end)
    if len(cs) < 500:
        return {"error": "too few bars (%d)" % len(cs)}
    st = get_settings()
    r = run_backtest(
        cs, MARKETS.get(key) or LOCAL_BACKTEST_MARKETS[key], starting_equity=100_000.0,
        risk_pct=st.risk.max_risk_per_trade_pct, atr_stop_mult=st.risk.atr_stop_multiplier,
        params=st.strategy, mc_runs=300, target_pct=10.0, total_limit_pct=9.0,
        rr=st.risk.default_rr, strategy={"name": "cs", "kind": "custom", "code": code},
        exo=exo, cost_pct=cost_pct,
    )
    d = r.to_dict()
    d["lin"] = linearity(d["equity_curve"])
    d["bars"] = len(cs)
    months = len(cs) * tf_min / (60.0 * 24.0 * 30.44)
    d["months"] = months
    d["rpm"] = d["total_return_pct"] / months if months > 0 else 0.0
    return d


HDR = "%-14s %6s %6s %5s %5s %7s %7s %6s %6s %5s %5s" % (
    "window", "bars", "trades", "win%", "PF", "ret%", "ret/mo", "dDD%", "tDD%", "R2", "MC%")


def show(label: str, code: str, windows, key="BTCUSD", tf_min=15, cost_pct=COST_PCT) -> None:
    print("\n=== %s — %s %dm  (cost %.2f%% RT) ===\n%s" % (label, key, tf_min, cost_pct, HDR))
    agg_rpm, worst_rpm, worst_tdd, worst_ddd = [], 999.0, 0.0, 0.0
    for nm, a, b in windows:
        d = run(code, key, tf_min, a, b, cost_pct)
        if d.get("error"):
            print("%-14s  %s" % (nm, d["error"]))
            continue
        mc = d["monte_carlo"]
        print("%-14s %6d %6d %5.1f %5.2f %7.2f %7.2f %6.2f %6.2f %5.2f %5s" % (
            nm, d["bars"], d["trades"], d["win_rate"], d["profit_factor"],
            d["total_return_pct"], d["rpm"], d["max_daily_dd_pct"],
            d["max_total_dd_pct"], d["lin"], mc.get("pass_prob_pct", "-")))
        agg_rpm.append(d["rpm"])
        worst_rpm = min(worst_rpm, d["rpm"])
        worst_tdd = max(worst_tdd, d["max_total_dd_pct"])
        worst_ddd = max(worst_ddd, d["max_daily_dd_pct"])
    if agg_rpm:
        print("%-14s mean ret/mo %.2f%%  worst window %.2f%%  worst dDD %.2f%%  worst tDD %.2f%%"
              % ("SUMMARY", sum(agg_rpm) / len(agg_rpm), worst_rpm, worst_ddd, worst_tdd))


# ── climate window sets ──────────────────────────────────────────────────────
HALVES = [
    ("2020H1 covid", "2020-01-01", "2020-07-01"),
    ("2020H2 bull0", "2020-07-01", "2021-01-01"),
    ("2021H1 mania", "2021-01-01", "2021-07-01"),
    ("2021H2 top", "2021-07-01", "2022-01-01"),
    ("2022H1 bear", "2022-01-01", "2022-07-01"),
    ("2022H2 ftx", "2022-07-01", "2023-01-01"),
    ("2023H1 rec", "2023-01-01", "2023-07-01"),
    ("2023H2 grind", "2023-07-01", "2024-01-01"),
    ("2024H1 etf", "2024-01-01", "2024-07-01"),
    ("2024H2 chop", "2024-07-01", "2025-01-01"),
    ("2025H1", "2025-01-01", "2025-07-01"),
    ("2025H2", "2025-07-01", "2026-01-01"),
    ("2026", "2026-01-01", None),
]
DEV = [HALVES[2], HALVES[5], HALVES[9], HALVES[12]]   # mania / ftx / chop / now
ONE = [("FULL 2020-26", None, None)]


# ── candidate snippets (appended as the R&D loop iterates) ───────────────────
def build_base_mk() -> str:
    # Baseline: the proven markov-scalper v3 logic (US500 champion) ported as-is.
    return '''
mk = markov(24, band=0.5, window=500)
edge = mk.edge
e200 = ema(200)
e50 = ema(50)
bull = edge > 0.05 and close > e50
bear = edge < -0.05 and close < e200
r = rsi(2)
a = atr(14)
wide = (high - low) > 3.5 * a if (a and a > 0) else True

halt = total_pnl_pct <= -6.0
day_locked = day_pnl_pct <= -3.0 or trades_today >= 60

risk = 0.75 + abs(edge) * 1.5
if dd_from_peak_pct >= 3.0:
    risk = risk * 0.5
if consec_losses >= 3:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked and not wide:
    if bull and r < 30:
        signal = "BUY"
    elif bear and r > 70:
        signal = "SELL"
elif position == 1:
    if r > 55 or bars_held >= 8 or edge < -0.08:
        signal = "FLAT"
elif position == -1:
    if r < 45 or bars_held >= 8 or edge > 0.08:
        signal = "FLAT"
'''


def build_c1() -> str:
    # CryptoState c1 — LONG-ONLY dual-horizon momentum ignition, flow-confirmed.
    # Probe basis (BTC 15m 6.4y): mom96 & mom24 & flow>0.03 -> +52.6bps/24h t=14.6;
    # ETH replicates. Shorts structurally negative (squeezes) -> long-only.
    return '''
h = hmm(3, 1000, 96)
mk96 = markov(96, band=1.0, window=800)
mk24 = markov(24, band=1.0, window=800)
f = flow_norm(20)

mom_ignite = mk96.state == "BULL" and mk24.state == "BULL"
flow_ok = (not isnan(f)) and f > 0.03
regime_ok = h.edge > -0.10

halt = total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 12

conv = min(1.0, max(0.0, (f - 0.03) * 12.0)) * 0.5 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
risk = 0.75 + conv * 0.75
if dd_from_peak_pct >= 3.0:
    risk = risk * 0.5
if consec_losses >= 3:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

stop_mult = 2.0
target_rr = 6.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if mom_ignite and flow_ok and regime_ok:
        signal = "BUY"
elif position == 1:
    if bars_held >= 96 or mk24.state == "BEAR" or h.edge < -0.25:
        signal = "FLAT"
'''


def build_c2() -> str:
    # CryptoState c2 — pullback-in-momentum: buy shallow dips inside a 96-bar
    # momentum state with positive flow (probe: +25-40bps/96 both symbols).
    return '''
h = hmm(3, 1000, 96)
mk96 = markov(96, band=1.0, window=800)
r8 = roc(8)
f = flow_norm(20)

mom_state = mk96.state == "BULL"
dip = (not isnan(r8)) and r8 < 0
flow_ok = (not isnan(f)) and f > 0.0
regime_ok = h.edge > -0.10

halt = total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 12

risk = 0.75 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
if dd_from_peak_pct >= 3.0:
    risk = risk * 0.5
if consec_losses >= 3:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.25)), 2)

stop_mult = 2.0
target_rr = 6.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if mom_state and dip and flow_ok and regime_ok:
        signal = "BUY"
elif position == 1:
    if bars_held >= 96 or mk96.state == "BEAR" or h.edge < -0.25:
        signal = "FLAT"
'''


def build_c3() -> str:
    # CryptoState c3 — RIDE THE STATE: long while the 96-bar momentum regime is
    # alive; wide disaster stop; exit only on state death. Anti-churn hysteresis:
    # strict entry (mom96+flow), loose exit (mom96 death / hard bear).
    return '''
h = hmm(3, 1000, 96)
mk96 = markov(96, band=1.0, window=800)
f = flow_norm(20)

enter = mk96.state == "BULL" and (not isnan(f)) and f > 0.01 and h.edge > -0.10
state_dead = mk96.state != "BULL"

halt = dd_from_peak_pct >= 7.0 or total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 8

risk = 1.0 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
if consec_losses >= 3:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

stop_mult = 4.0
target_rr = 4.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if state_dead or h.edge < -0.30:
        signal = "FLAT"
'''


def build_c4() -> str:
    # c3 + stricter onset (mom24 aligned too) but SAME loose exit (hysteresis).
    return '''
h = hmm(3, 1000, 96)
mk96 = markov(96, band=1.0, window=800)
mk24 = markov(24, band=1.0, window=800)
f = flow_norm(20)

enter = (mk96.state == "BULL" and mk24.state == "BULL"
         and (not isnan(f)) and f > 0.01 and h.edge > -0.10)
state_dead = mk96.state != "BULL"

halt = dd_from_peak_pct >= 7.0 or total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 8

risk = 1.0 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
if consec_losses >= 3:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

stop_mult = 4.0
target_rr = 4.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if state_dead or h.edge < -0.30:
        signal = "FLAT"
'''


def build_c5() -> str:
    # c5 — DEEP HYSTERESIS on an explicit momentum z-score: enter z96>1 (with
    # 24-bar alignment + flow), exit only when momentum is truly dead (z96<0.1).
    # z = roc(N) / (sigma * sqrt(N)); sigma ~= atr%(14)/1.5 (calibrated on BTC 15m).
    return '''
h = hmm(3, 1000, 96)
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r96 = roc(96)
r24 = roc(24)
f = flow_norm(20)

z96 = r96 / (atrp * 6.53) if (not isnan(atrp)) and atrp > 0 else nan
z24 = r24 / (atrp * 3.27) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z96) or isnan(z24) or isnan(f))
enter = ok and z96 > 1.0 and z24 > 0.5 and f > 0.01 and h.edge > -0.10
mom_dead = ok and z96 < 0.1

halt = dd_from_peak_pct >= 7.0 or total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 8

risk = 1.0 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
if consec_losses >= 3:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

stop_mult = 4.0
target_rr = 4.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if mom_dead or h.edge < -0.30:
        signal = "FLAT"
'''


def build_c6() -> str:
    # c6 = c5 + higher-timeframe trend gate (4-day SMA) to stop buying bear
    # rallies, stricter flow, deeper exit hysteresis (z96<0).
    return '''
h = hmm(3, 1000, 96)
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r96 = roc(96)
r24 = roc(24)
f = flow_norm(20)
trend = sma(384)

z96 = r96 / (atrp * 6.53) if (not isnan(atrp)) and atrp > 0 else nan
z24 = r24 / (atrp * 3.27) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z96) or isnan(z24) or isnan(f) or isnan(trend))
enter = (ok and z96 > 1.0 and z24 > 0.5 and f > 0.02
         and h.edge > -0.10 and close > trend)
mom_dead = ok and z96 < 0.0

halt = dd_from_peak_pct >= 7.0 or total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 6

risk = 1.0 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
if consec_losses >= 3:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

stop_mult = 4.0
target_rr = 4.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if mom_dead or h.edge < -0.30:
        signal = "FLAT"
'''


def build_c7() -> str:
    # c7 — strict dual-horizon IGNITION (fast z24 leads), probe-exact 96-bar
    # hold, fast bail on hard reversal. The probe's richest pocket.
    return '''
h = hmm(3, 1000, 96)
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r96 = roc(96)
r24 = roc(24)
f = flow_norm(20)
trend = sma(384)

z96 = r96 / (atrp * 6.53) if (not isnan(atrp)) and atrp > 0 else nan
z24 = r24 / (atrp * 3.27) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z96) or isnan(z24) or isnan(f) or isnan(trend))
enter = (ok and z96 > 1.0 and z24 > 1.0 and f > 0.03
         and h.edge > -0.10 and close > trend)

halt = dd_from_peak_pct >= 7.0 or total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 6

risk = 1.0 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
if consec_losses >= 3:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

stop_mult = 4.0
target_rr = 4.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if bars_held >= 96 or (ok and z24 < -0.5) or h.edge < -0.30:
        signal = "FLAT"
'''


def build_c8() -> str:
    # c8 = c6 + slow 3-day markov regime veto (blocks bear-rally longs) +
    # extension cap on the fast horizon (don't chase z24>1.5) + flow 0.03.
    return '''
h = hmm(3, 1000, 96)
mk288 = markov(288, band=0.5, window=1400)
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r96 = roc(96)
r24 = roc(24)
f = flow_norm(20)
trend = sma(384)

z96 = r96 / (atrp * 6.53) if (not isnan(atrp)) and atrp > 0 else nan
z24 = r24 / (atrp * 3.27) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z96) or isnan(z24) or isnan(f) or isnan(trend))
enter = (ok and z96 > 1.0 and z24 > 0.5 and z24 < 1.5 and f > 0.03
         and h.edge > -0.10 and close > trend and mk288.state != "BEAR")
mom_dead = ok and z96 < 0.0

halt = dd_from_peak_pct >= 7.0 or total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 6

risk = 1.0 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
if consec_losses >= 3:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

stop_mult = 4.0
target_rr = 4.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if mom_dead or h.edge < -0.30:
        signal = "FLAT"
'''


def build_c9() -> str:
    # c9 — c6 entries + MOMENTUM-HARVEST exits: 3-ATR price trail from entry
    # (caps giveback, rides fat tails), wide 4-ATR disaster stop, far target,
    # hard-reversal bail only. No streak throttle (momentum win rates are low
    # by nature; streak-halving starves the winners).
    return '''
h = hmm(3, 1000, 96)
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r96 = roc(96)
r24 = roc(24)
f = flow_norm(20)
trend = sma(384)

z96 = r96 / (atrp * 6.53) if (not isnan(atrp)) and atrp > 0 else nan
z24 = r24 / (atrp * 3.27) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z96) or isnan(z24) or isnan(f) or isnan(trend))
enter = (ok and z96 > 1.0 and z24 > 0.5 and f > 0.02
         and h.edge > -0.10 and close > trend)

halt = dd_from_peak_pct >= 7.0 or total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 6

risk = 1.0 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

stop_mult = 4.0
target_rr = 8.0
trail_dist = 3.0 * a if (a and a > 0) else None

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if (ok and z24 < -1.0) or h.edge < -0.30:
        signal = "FLAT"
'''


def build_c10() -> str:
    # c10 — ONSET-ONLY entries: fire only on the bar the momentum z-score
    # CROSSES its threshold (fresh ignition), never on state presence.
    # Kills re-entry churn structurally. Exits = c6 hysteresis giveback.
    return '''
h = hmm(3, 1000, 96)
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
atrp_p = 100.0 * a.prev / close.prev if (a and a.prev > 0) else nan
r96 = roc(96)
r24 = roc(24)
f = flow_norm(20)
trend = sma(384)

z96 = r96 / (atrp * 6.53) if (not isnan(atrp)) and atrp > 0 else nan
z96p = r96.prev / (atrp_p * 6.53) if (not isnan(atrp_p)) and atrp_p > 0 else nan
z24 = r24 / (atrp * 3.27) if (not isnan(atrp)) and atrp > 0 else nan
z24p = r24.prev / (atrp_p * 3.27) if (not isnan(atrp_p)) and atrp_p > 0 else nan

ok = not (isnan(z96) or isnan(z96p) or isnan(z24) or isnan(z24p) or isnan(f) or isnan(trend))
fresh96 = ok and z96p <= 1.0 and z96 > 1.0 and z24 > 0.0
fresh24 = ok and z24p <= 0.8 and z24 > 0.8 and z96 > 1.0
enter = (fresh96 or fresh24) and f > 0.02 and h.edge > -0.10 and close > trend

halt = dd_from_peak_pct >= 7.0 or total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 6

risk = 1.0 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

stop_mult = 4.0
target_rr = 6.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if (ok and z96 < 0.0) or h.edge < -0.30:
        signal = "FLAT"
'''


def build_c11() -> str:
    # c11 = c6 + the probe-decisive MACRO overlay (50-day daily SMA): the 15m
    # momentum edge ONLY exists above it (+52.6bps t=19.8 vs -8.7bps below).
    return '''
h = hmm(3, 1000, 96)
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r96 = roc(96)
r24 = roc(24)
f = flow_norm(20)

z96 = r96 / (atrp * 6.53) if (not isnan(atrp)) and atrp > 0 else nan
z24 = r24 / (atrp * 3.27) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z96) or isnan(z24) or isnan(f) or isnan(macro))
enter = (ok and macro > 0.0 and z96 > 1.0 and z24 > 0.5 and f > 0.02
         and h.edge > -0.10)
mom_dead = ok and z96 < 0.0

halt = dd_from_peak_pct >= 7.0 or total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 6

risk = 1.0 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

stop_mult = 4.0
target_rr = 4.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if mom_dead or h.edge < -0.30:
        signal = "FLAT"
'''


def build_c12() -> str:
    # c12 = c10 onset-only entries + the MACRO overlay.
    return '''
h = hmm(3, 1000, 96)
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
atrp_p = 100.0 * a.prev / close.prev if (a and a.prev > 0) else nan
r96 = roc(96)
r24 = roc(24)
f = flow_norm(20)

z96 = r96 / (atrp * 6.53) if (not isnan(atrp)) and atrp > 0 else nan
z96p = r96.prev / (atrp_p * 6.53) if (not isnan(atrp_p)) and atrp_p > 0 else nan
z24 = r24 / (atrp * 3.27) if (not isnan(atrp)) and atrp > 0 else nan
z24p = r24.prev / (atrp_p * 3.27) if (not isnan(atrp_p)) and atrp_p > 0 else nan

ok = not (isnan(z96) or isnan(z96p) or isnan(z24) or isnan(z24p) or isnan(f) or isnan(macro))
fresh96 = ok and z96p <= 1.0 and z96 > 1.0 and z24 > 0.0
fresh24 = ok and z24p <= 0.8 and z24 > 0.8 and z96 > 1.0
enter = (fresh96 or fresh24) and macro > 0.0 and f > 0.02 and h.edge > -0.10

halt = dd_from_peak_pct >= 7.0 or total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 6

risk = 1.0 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

stop_mult = 4.0
target_rr = 6.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if (ok and z96 < 0.0) or h.edge < -0.30:
        signal = "FLAT"
'''


def build_c13() -> str:
    # c13 = c6 full entry stack (incl. local sma384 timing gate) + MACRO DEPTH
    # (>3% above the 50-day daily SMA -> filters SMA-whipsaw years like 2026).
    return '''
h = hmm(3, 1000, 96)
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r96 = roc(96)
r24 = roc(24)
f = flow_norm(20)
trend = sma(384)

z96 = r96 / (atrp * 6.53) if (not isnan(atrp)) and atrp > 0 else nan
z24 = r24 / (atrp * 3.27) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z96) or isnan(z24) or isnan(f) or isnan(trend) or isnan(macro))
enter = (ok and macro > 3.0 and z96 > 1.0 and z24 > 0.5 and f > 0.02
         and h.edge > -0.10 and close > trend)
mom_dead = ok and z96 < 0.0

halt = dd_from_peak_pct >= 7.0 or total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 6

risk = 1.0 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

stop_mult = 4.0
target_rr = 4.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if mom_dead or h.edge < -0.30:
        signal = "FLAT"
'''


def build_c15() -> str:
    # c15 = c13 + SECULAR overlay (200-day daily SMA): full dual-momentum stack.
    # Blocks the last loss pocket — relief-rally tops inside secular bears.
    return '''
h = hmm(3, 1000, 96)
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
         and f > 0.02 and h.edge > -0.10 and close > trend)
mom_dead = ok and z96 < 0.0

halt = dd_from_peak_pct >= 7.0 or total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 6

risk = 1.0 + min(1.0, max(0.0, h.edge * 2.0)) * 0.5
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

stop_mult = 4.0
target_rr = 4.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if mom_dead or h.edge < -0.30:
        signal = "FLAT"
'''


def build_c15x() -> str:
    # ABLATION: c15 without the HMM gate/conviction (fixed risk) — measures the
    # HMM's marginal contribution for the report.
    return '''
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

halt = dd_from_peak_pct >= 7.0 or total_pnl_pct <= -6.5
day_locked = day_pnl_pct <= -2.5 or trades_today >= 6

risk = 1.25
if dd_from_peak_pct >= 3.5:
    risk = 0.6

stop_mult = 4.0
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
'''


def _engine(macro_min: float, flow_min: float, z24_min: float) -> str:
    # Shared c16-family engine: c15x signal stack + graduated streak/dd risk
    # curve (a 7-loss streak costs ~4.5%, never reaches the halt) + halts with
    # buffer inside the 9% internal ceiling.
    return f'''
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r96 = roc(96)
r24 = roc(24)
f = flow_norm(20)
trend = sma(384)

z96 = r96 / (atrp * 6.53) if (not isnan(atrp)) and atrp > 0 else nan
z24 = r24 / (atrp * 3.27) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z96) or isnan(z24) or isnan(f) or isnan(trend) or isnan(macro) or isnan(macro_slow))
enter = (ok and macro > {macro_min} and macro_slow > 0.0 and z96 > 1.0
         and z24 > {z24_min} and f > {flow_min} and close > trend)
mom_dead = ok and z96 < 0.0

halt = dd_from_peak_pct >= 7.5 or total_pnl_pct <= -7.0
day_locked = day_pnl_pct <= -2.5 or trades_today >= 6

risk = 1.1
if consec_losses >= 4:
    risk = risk * 0.35
elif consec_losses >= 2:
    risk = risk * 0.6
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.3, risk), 2)

stop_mult = 4.0
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
'''


def build_c16() -> str:
    return _engine(3.0, 0.02, 0.5)


def build_c17() -> str:
    # frequency-relaxed: looser in-regime gates, same risk curve
    return _engine(1.5, 0.01, 0.3)


def build_c18() -> str:
    # c18 = c16 + FRESH-HIGH requirement (4-day breakout): kills range-top
    # false ignitions (the 2023H2 failure mode) — a z-spike inside a chop range
    # is not tradable momentum; a z-spike AT a fresh multi-day high is.
    return '''
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r96 = roc(96)
r24 = roc(24)
f = flow_norm(20)
hh = highest(384)

z96 = r96 / (atrp * 6.53) if (not isnan(atrp)) and atrp > 0 else nan
z24 = r24 / (atrp * 3.27) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z96) or isnan(z24) or isnan(f) or isnan(hh) or isnan(macro) or isnan(macro_slow))
enter = (ok and macro > 3.0 and macro_slow > 0.0 and z96 > 1.0 and z24 > 0.5
         and f > 0.02 and close > hh.prev)
mom_dead = ok and z96 < 0.0

halt = dd_from_peak_pct >= 7.5 or total_pnl_pct <= -7.0
day_locked = day_pnl_pct <= -2.5 or trades_today >= 6

risk = 1.1
if consec_losses >= 4:
    risk = risk * 0.35
elif consec_losses >= 2:
    risk = risk * 0.6
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.3, risk), 2)

stop_mult = 4.0
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
'''


def build_c19() -> str:
    # c19 = c16 + dynamic stop FLOOR (>=2.2% of price): in ATR-compressed chop
    # the 4-ATR stop sits inside the range's natural swing — floor it so the
    # z-giveback exit manages chop losers instead of full-R stop-outs.
    return '''
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
day_locked = day_pnl_pct <= -2.5 or trades_today >= 6

risk = 1.1
if consec_losses >= 4:
    risk = risk * 0.35
elif consec_losses >= 2:
    risk = risk * 0.6
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.3, risk), 2)

stop_mult = min(5.0, max(4.0, 2.2 / atrp)) if (ok and atrp > 0) else 4.0
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
'''


def _engine_final(base_risk: float) -> str:
    # c20-family: c19 signal stack, day lock tightened to protect the 4% daily
    # ceiling, stop floor capped at 4.5 ATR, parameterized base risk for the
    # scaling sweep.
    return f'''
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

risk = {base_risk}
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
'''


def build_c20() -> str:
    return _engine_final(1.1)


def build_c20s() -> str:
    # scaled: aggressive base risk occupying the remaining DD runway
    return _engine_final(1.6)


BUILDS = {"base_mk": build_base_mk, "c1": build_c1, "c2": build_c2,
          "c3": build_c3, "c4": build_c4, "c5": build_c5, "c6": build_c6,
          "c7": build_c7, "c8": build_c8, "c9": build_c9, "c10": build_c10,
          "c11": build_c11, "c12": build_c12, "c13": build_c13,
          "c15": build_c15, "c15x": build_c15x,
          "c16": build_c16, "c17": build_c17, "c18": build_c18,
          "c19": build_c19, "c20": build_c20, "c20s": build_c20s}

if __name__ == "__main__":
    ver = sys.argv[1] if len(sys.argv) > 1 else "base_mk"
    which = sys.argv[2] if len(sys.argv) > 2 else "dev"
    cost = float(sys.argv[3]) if len(sys.argv) > 3 else COST_PCT
    code = BUILDS[ver]()
    if which == "dev":
        show(ver, code, DEV, "BTCUSD", 15, cost)
    elif which == "full":
        show(ver, code, HALVES, "BTCUSD", 15, cost)
    elif which == "one":
        show(ver, code, ONE, "BTCUSD", 15, cost)
    elif which == "eth":
        show(ver, code, HALVES, "ETHUSD", 15, cost)
    elif which == "etdev":
        show(ver, code, DEV, "ETHUSD", 15, cost)
    elif which == "btc5":
        show(ver, code, HALVES[6:], "BTCUSD", 5, cost)
    elif which == "eth5":
        show(ver, code, HALVES[6:], "ETHUSD", 5, cost)
    elif which == "btc60":
        show(ver, code, HALVES, "BTCUSD", 60, cost)
    elif which == "btc1":
        show(ver, code, HALVES[10:], "BTCUSD", 1, cost)
