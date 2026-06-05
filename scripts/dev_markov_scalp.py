"""Dev-only iterative harness for the Markov-regime scalper.

Loads the local intraday series, slices by DATE WINDOW (walk-forward across
real climates), runs the candidate snippet through the backtest engine, and
reports growth + smoothness: return, daily/total drawdown, a linearity R^2 of
the equity curve (how close to a straight line up — the user's key ask), and the
Monte-Carlo probability of +10% before -10%.

Run:  venv/Scripts/python.exe scripts/dev_markov_scalp.py [vN] [us500|climate|deep]
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

_CACHE: dict = {}


def full(key: str, tf: str):
    if (key, tf) not in _CACHE:
        _CACHE[(key, tf)] = dataset.load(key, 0, timeframe=tf)
    return _CACHE[(key, tf)]


def market_for(key: str):
    return MARKETS.get(key) or LOCAL_BACKTEST_MARKETS.get(key)


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
    """R^2 of equity vs time — 1.0 = a perfectly straight line up/down."""
    n = len(eq)
    if n < 3:
        return 0.0
    xs = list(range(n))
    ys = [p["equity"] for p in eq]
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return round((sxy * sxy) / (sxx * syy), 3)


def run(code: str, key: str, tf_min: int, start=None, end=None) -> dict:
    tf = dataset.suffix_for(tf_min)
    s = full(key, tf)
    cs, exo = _slice(s, start, end)
    if len(cs) < 120:
        return {"error": "too few bars (%d)" % len(cs)}
    st = get_settings()
    r = run_backtest(
        cs, market_for(key), starting_equity=100_000.0,
        risk_pct=st.risk.max_risk_per_trade_pct, atr_stop_mult=st.risk.atr_stop_multiplier,
        params=st.strategy, mc_runs=200, target_pct=10.0, total_limit_pct=10.0,
        rr=st.risk.default_rr, strategy={"name": "mk", "kind": "custom", "code": code}, exo=exo,
    )
    d = r.to_dict()
    d["lin"] = linearity(d["equity_curve"])
    d["bars"] = len(cs)
    return d


HDR = "%-20s %5s %6s %5s %6s %8s %6s %6s %5s %6s %6s" % (
    "window", "bars", "trades", "win%", "PF", "ret%", "dDD%", "tDD%", "R2", "MCpas", "MCbr")


def show(label: str, code: str, windows, key="US500", tf_min=5) -> None:
    print("\n=== %s — %s %dm ===\n%s" % (label, key, tf_min, HDR))
    for nm, a, b in windows:
        d = run(code, key, tf_min, a, b)
        if d.get("error"):
            print("%-20s  %s" % (nm, d["error"]))
            continue
        mc = d["monte_carlo"]
        print("%-20s %5d %6d %5.1f %6.2f %8.2f %6.2f %6.2f %5.2f %6s %6s" % (
            nm, d["bars"], d["trades"], d["win_rate"], d["profit_factor"],
            d["total_return_pct"], d["max_daily_dd_pct"], d["max_total_dd_pct"],
            d["lin"], mc.get("pass_prob_pct", "-"), mc.get("breach_prob_pct", "-")))


# ── window sets ──────────────────────────────────────────────────────────────
US500_5M = [
    ("ALL 03-11..06-04", None, None),
    ("A 03-11..04-15", "2026-03-11", "2026-04-15"),
    ("B 04-15..05-10", "2026-04-15", "2026-05-10"),
    ("C 05-10..06-04", "2026-05-10", None),
]
US500_CLIMATE_60M = [
    ("ALL 2023-07..2026", None, None),
    ("2023H2", "2023-07-01", "2024-01-01"),
    ("2024H1", "2024-01-01", "2024-07-01"),
    ("2024H2", "2024-07-01", "2025-01-01"),
    ("2025H1", "2025-01-01", "2025-07-01"),
    ("2025H2", "2025-07-01", "2026-01-01"),
    ("2026", "2026-01-01", None),
]


# ── candidate versions (kept so we can compare) ──────────────────────────────
def build_v1() -> str:
    return '''
mk = markov(20, band=0.6, window=600)
edge = mk.edge
bull = edge > 0.10
bear = edge < -0.10
u, mid, l = bollinger(20, 2.0)
r = rsi(2)
a = atr(14)
wide = (high - low) > 3.0 * a if (a and a > 0) else True

survival = dd_from_peak_pct >= 7.0
day_locked = day_pnl_pct <= -3.0 or trades_today >= 40

risk = round(max(0.5, min(0.75 + abs(edge) * 2.5, 2.0)), 2)
if consec_losses >= 3:
    risk = round(risk * 0.5, 2)

signal = "HOLD"
if survival:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked and not wide:
    if bull:
        if r < 25 or close <= l:
            signal = "BUY"
    elif bear:
        if r > 75 or close >= u:
            signal = "SELL"
    else:
        if r < 5 and close <= l:
            signal = "BUY"
        elif r > 95 and close >= u:
            signal = "SELL"
elif position == 1:
    if r > 60 or bars_held >= 12 or bear:
        signal = "FLAT"
elif position == -1:
    if r < 40 or bars_held >= 12 or bull:
        signal = "FLAT"
'''


def build_v2() -> str:
    return '''
mk = markov(24, band=0.5, window=500)
edge = mk.edge
e200 = ema(200)
e50 = ema(50)
trend_up = close > e200 and e50 > e200
trend_dn = close < e200 and e50 < e200
bull = edge > 0.05 and trend_up
bear = edge < -0.05 and trend_dn
u, mid, l = bollinger(20, 2.2)
r = rsi(2)
a = atr(14)
wide = (high - low) > 3.5 * a if (a and a > 0) else True

halt = total_pnl_pct <= -8.0
day_locked = day_pnl_pct <= -3.5 or trades_today >= 60

risk = 0.75 + abs(edge) * 2.0
if dd_from_peak_pct >= 4.0:
    risk = risk * 0.5
if consec_losses >= 3:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 2.0)), 2)

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked and not wide:
    if bull:
        if r < 35:
            signal = "BUY"
    elif bear:
        if r > 65:
            signal = "SELL"
    else:
        if r < 8 and close <= l:
            signal = "BUY"
        elif r > 92 and close >= u:
            signal = "SELL"
elif position == 1:
    if r > 55 or bars_held >= 10 or edge < -0.10:
        signal = "FLAT"
elif position == -1:
    if r < 45 or bars_held >= 10 or edge > 0.10:
        signal = "FLAT"
'''


def build_v3() -> str:
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

halt = total_pnl_pct <= -8.0
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


def build_v4() -> str:
    return '''
mk = markov(24, band=0.5, window=500)
edge = mk.edge
stick = mk.stickiness
e200 = ema(200)
e50 = ema(50)
persist = stick >= 0.55
bull = edge > 0.05 and close > e50 and persist
bear = edge < -0.05 and close < e200 and persist
r = rsi(2)
a = atr(14)
wide = (high - low) > 3.5 * a if (a and a > 0) else True

halt = total_pnl_pct <= -8.0
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


def build_v5() -> str:
    return '''
mk = markov(24, band=0.5, window=500)
edge = mk.edge
e200 = ema(200)
e50 = ema(50)
up = close > e200 and e50 > e200
dn = close < e200 and e50 < e200
bull = edge > 0.05 and up
bear = edge < -0.05 and dn
r = rsi(2)
a = atr(14)
wide = (high - low) > 3.5 * a if (a and a > 0) else True

halt = total_pnl_pct <= -8.0
day_locked = day_pnl_pct <= -3.0 or trades_today >= 60

risk = 0.75 + abs(edge) * 1.5
if dd_from_peak_pct >= 3.0:
    risk = risk * 0.5
if consec_losses >= 2:
    risk = risk * 0.5
risk = round(max(0.4, min(risk, 1.5)), 2)

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked and not wide:
    if bull and r < 25:
        signal = "BUY"
    elif bear and r > 75:
        signal = "SELL"
elif position == 1:
    if r > 55 or bars_held >= 8 or edge < -0.05:
        signal = "FLAT"
elif position == -1:
    if r < 45 or bars_held >= 8 or edge > 0.05:
        signal = "FLAT"
'''


def build_v6() -> str:
    # v3 (the robust winner) + earlier drawdown-aware de-risking for a smoother curve.
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

halt = total_pnl_pct <= -8.0
day_locked = day_pnl_pct <= -3.0 or trades_today >= 60

risk = 0.75 + abs(edge) * 1.5
if dd_from_peak_pct >= 2.5:
    risk = risk * 0.5
if consec_losses >= 2:
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


def build_v7() -> str:
    # v3 logic, risk pushed into the user's 1-3% band (conviction-scaled, capped 2.5).
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

halt = total_pnl_pct <= -8.0
day_locked = day_pnl_pct <= -3.5 or trades_today >= 60

risk = 1.0 + abs(edge) * 2.0
if dd_from_peak_pct >= 3.0:
    risk = risk * 0.5
if consec_losses >= 2:
    risk = risk * 0.5
risk = round(max(0.5, min(risk, 2.5)), 2)

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


BUILDS = {"v1": build_v1, "v2": build_v2, "v3": build_v3,
          "v4": build_v4, "v5": build_v5, "v6": build_v6, "v7": build_v7}

if __name__ == "__main__":
    ver = sys.argv[1] if len(sys.argv) > 1 else "v7"
    which = sys.argv[2] if len(sys.argv) > 2 else "us500"
    code = BUILDS[ver]()
    if which in ("us500", "all"):
        show(ver, code, US500_5M, "US500", 5)
    if which in ("climate", "all"):
        show(ver, code, US500_CLIMATE_60M, "US500", 60)
    if which == "deep":
        show(ver, code, [("EURUSD all", None, None)], "EURUSD", 5)
        show(ver, code, [("BTC all", None, None)], "BTCUSD", 5)
