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
from apex.config import MARKETS, Market, Regime, get_settings  # noqa: E402

# Harness-local markets for instruments not in the live universe (Dukascopy data).
_LOCAL_MK = {
    "XAUUSD": Market("XAUUSD", "Gold", "CMD.XAUUSD", 1.0, 30, "00:00", "23:59", Regime.TRENDING, 0.3),
}

_CACHE: dict = {}


def full(key: str, tf: str):
    if (key, tf) not in _CACHE:
        _CACHE[(key, tf)] = dataset.load(key, 0, timeframe=tf)
    return _CACHE[(key, tf)]


def market_for(key: str):
    return MARKETS.get(key) or LOCAL_BACKTEST_MARKETS.get(key) or _LOCAL_MK.get(key)


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


# Realistic round-trip transaction cost (spread + commission) in PRICE units, per
# instrument (raw/prop account). Big-move trend trades barely feel these.
_COST = {
    "EURUSD": 0.00008, "GBPUSD": 0.00008, "USDJPY": 0.012,
    "US500": 0.5, "NAS100": 2.0, "US2000": 0.5,
    "BTCUSD": 30.0, "ETHUSD": 2.0, "XAUUSD": 0.4, "USOIL": 0.05,
}


def _cost_points(key: str) -> float:
    return _COST.get(key, 0.5)


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
        cost_points=_cost_points(key),
    )
    d = r.to_dict()
    d["lin"] = linearity(d["equity_curve"])
    d["bars"] = len(cs)
    return d


HDR = "%-18s %5s %6s %5s %5s %5s %5s %8s %6s %6s %5s %6s" % (
    "window", "bars", "trades", "win%", "PF", "RR", "BEwn", "ret%", "dDD%", "tDD%", "R2", "MCps")


def show(label: str, code: str, windows, key="US500", tf_min=5) -> None:
    print("\n=== %s — %s %dm ===\n%s" % (label, key, tf_min, HDR))
    for nm, a, b in windows:
        d = run(code, key, tf_min, a, b)
        if d.get("error"):
            print("%-18s  %s" % (nm, d["error"]))
            continue
        mc = d["monte_carlo"]
        rr = d["avg_rr"]
        bewin = 100.0 / (1.0 + rr) if rr > 0 else 0.0   # break-even win% for this R:R
        print("%-18s %5d %6d %5.1f %5.2f %5.2f %5.1f %8.2f %6.2f %6.2f %5.2f %6s" % (
            nm, d["bars"], d["trades"], d["win_rate"], d["profit_factor"], rr, bewin,
            d["total_return_pct"], d["max_daily_dd_pct"], d["max_total_dd_pct"],
            d["lin"], mc.get("pass_prob_pct", "-")))


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
EUR_5M = [
    ("ALL 03-16..06-04", None, None),
    ("A 03-16..04-10", "2026-03-16", "2026-04-10"),
    ("B 04-10..05-05", "2026-04-10", "2026-05-05"),
    ("C 05-05..06-04", "2026-05-05", None),
]
EUR_CLIMATE_60M = [
    ("ALL 2023-08..2026", None, None),
    ("2023H2", "2023-08-01", "2024-01-01"),
    ("2024H1", "2024-01-01", "2024-07-01"),
    ("2024H2", "2024-07-01", "2025-01-01"),
    ("2025H1", "2025-01-01", "2025-07-01"),
    ("2025H2", "2025-07-01", "2026-01-01"),
    ("2026", "2026-01-01", None),
]
# Daily windows (20y) spanning many macro regimes — for the higher-TF swing search.
DAILY = [
    ("ALL", None, None),
    ("2008-2011", "2008-01-01", "2012-01-01"),
    ("2012-2015", "2012-01-01", "2016-01-01"),
    ("2016-2019", "2016-01-01", "2020-01-01"),
    ("2020-2022", "2020-01-01", "2023-01-01"),
    ("2023-2026", "2023-01-01", None),
]
# US500 intraday half-years available in US500_60m (2023-07 onward).
US_DEEP = [
    ("2023H2", "2023-07-01", "2024-01-01"),
    ("2024H1", "2024-01-01", "2024-07-01"),
    ("2024H2", "2024-07-01", "2025-01-01"),
    ("2025H1", "2025-01-01", "2025-07-01"),
    ("2025H2", "2025-07-01", "2026-01-01"),
    ("2026", "2026-01-01", None),
]
# Deep real Dukascopy EURUSD half-year climates (2023-2026), usable at 5m or 15m.
EUR_DEEP = [
    ("2023H1", "2023-01-01", "2023-07-01"),
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


def build_v2a() -> str:
    # Safer v2: keep v3's growth engine + sizing, but (a) cut non-bouncing losers
    # fast (synthetic tight stop -> better R:R), (b) let winners run (r>70 exit),
    # (c) tighter daily cap -2%, (d) de-risk after 2 losses / 4% peak DD.
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
day_locked = day_pnl_pct <= -2.0 or trades_today >= 60

risk = 0.75 + abs(edge) * 1.5
if dd_from_peak_pct >= 4.0:
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
    if (bars_held >= 3 and r < 15) or r > 70 or bars_held >= 12 or edge < -0.08:
        signal = "FLAT"
elif position == -1:
    if (bars_held >= 3 and r > 85) or r < 30 or bars_held >= 12 or edge > 0.08:
        signal = "FLAT"
'''


def build_v2b() -> str:
    # v3's exact winning trade logic + ONLY safety: daily cap -2%, tiered de-risk.
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
day_locked = day_pnl_pct <= -2.0 or trades_today >= 60

risk = 0.75 + abs(edge) * 1.5
if dd_from_peak_pct >= 6.0:
    risk = risk * 0.25
elif dd_from_peak_pct >= 4.0:
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


def build_v2c() -> str:
    # v2b safety + gentle R:R lift: let winners run to r>65 / r<35 (loser side untouched).
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
day_locked = day_pnl_pct <= -2.0 or trades_today >= 60

risk = 0.75 + abs(edge) * 1.5
if dd_from_peak_pct >= 6.0:
    risk = risk * 0.25
elif dd_from_peak_pct >= 4.0:
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
    if r > 65 or bars_held >= 10 or edge < -0.08:
        signal = "FLAT"
elif position == -1:
    if r < 35 or bars_held >= 10 or edge > 0.08:
        signal = "FLAT"
'''


def build_m1() -> str:
    # Momentum/trend with markov regime: FEW, BIG trades so the ~0.8pip cost is a
    # small fraction of each move. Enter on a shallow pullback in a strong,
    # persistent, trending regime; let the ATR stop / RR target run; exit on flip.
    return '''
mk = markov(24, band=0.5, window=500)
edge = mk.edge
e50 = ema(50)
e200 = ema(200)
adx_v = adx(14)
r = rsi(2)

strong_bull = edge > 0.15 and close > e200 and e50 > e200 and adx_v > 20
strong_bear = edge < -0.15 and close < e200 and e50 < e200 and adx_v > 20

halt = total_pnl_pct <= -8.0
day_locked = day_pnl_pct <= -3.0

risk = round(max(0.4, min(0.5 + abs(edge) * 1.5, 1.5)), 2)

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if strong_bull and r < 40:
        signal = "BUY"
    elif strong_bear and r > 60:
        signal = "SELL"
elif position == 1:
    if edge < -0.05 or bars_held >= 40:
        signal = "FLAT"
elif position == -1:
    if edge > 0.05 or bars_held >= 40:
        signal = "FLAT"
'''


def build_s1() -> str:
    # Higher-TF swing: markov-regime trend-pullback. Buy dips in a confirmed,
    # persistent up-regime (mirror for shorts); ride to a regime flip. Few trades,
    # big moves -> costs negligible. The proper "hedge-fund markov" trend method.
    return '''
mk = markov(20, band=0.5, window=400)
edge = mk.edge
e50 = ema(50)
e200 = ema(200)
r = rsi(2)
up = edge > 0.10 and close > e200 and e50 > e200
dn = edge < -0.10 and close < e200 and e50 < e200

halt = total_pnl_pct <= -8.0
risk = round(max(0.5, min(0.75 + abs(edge) * 1.5, 2.0)), 2)

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0:
    if up and r < 30:
        signal = "BUY"
    elif dn and r > 70:
        signal = "SELL"
elif position == 1:
    if edge < 0.0 or r > 85:
        signal = "FLAT"
elif position == -1:
    if edge > 0.0 or r < 15:
        signal = "FLAT"
'''


def build_s2() -> str:
    # s1 with a looser entry (edge>0.06, just close>EMA200, RSI<35) for more trades.
    return '''
mk = markov(20, band=0.5, window=400)
edge = mk.edge
e200 = ema(200)
r = rsi(2)
up = edge > 0.06 and close > e200
dn = edge < -0.06 and close < e200

halt = total_pnl_pct <= -8.0
risk = round(max(0.5, min(0.75 + abs(edge) * 1.5, 2.0)), 2)

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0:
    if up and r < 35:
        signal = "BUY"
    elif dn and r > 65:
        signal = "SELL"
elif position == 1:
    if edge < -0.02 or r > 80:
        signal = "FLAT"
elif position == -1:
    if edge > 0.02 or r < 20:
        signal = "FLAT"
'''


def build_s3() -> str:
    # s2 + higher quality: deeper dips (RSI<20), trend structure (EMA50>EMA200),
    # gentler risk capped 1.5% so one bad small-sample window can't blow up.
    return '''
mk = markov(20, band=0.5, window=400)
edge = mk.edge
e50 = ema(50)
e200 = ema(200)
r = rsi(2)
up = edge > 0.06 and close > e200 and e50 > e200
dn = edge < -0.06 and close < e200 and e50 < e200

halt = total_pnl_pct <= -8.0
risk = round(max(0.5, min(0.6 + abs(edge) * 1.0, 1.5)), 2)

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0:
    if up and r < 20:
        signal = "BUY"
    elif dn and r > 80:
        signal = "SELL"
elif position == 1:
    if edge < -0.02 or r > 80:
        signal = "FLAT"
elif position == -1:
    if edge > 0.02 or r < 20:
        signal = "FLAT"
'''


def build_s4() -> str:
    # FINAL candidate: s2's edge, FTMO-bulletproofed — risk cap 1.5%, earlier -6%
    # total-loss stop (never approaches -10%), daily cap -4%.
    return '''
mk = markov(20, band=0.5, window=400)
edge = mk.edge
e200 = ema(200)
r = rsi(2)
up = edge > 0.06 and close > e200
dn = edge < -0.06 and close < e200

halt = total_pnl_pct <= -6.0
day_locked = day_pnl_pct <= -4.0

risk = round(max(0.5, min(0.6 + abs(edge) * 1.2, 1.5)), 2)

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if up and r < 35:
        signal = "BUY"
    elif dn and r > 65:
        signal = "SELL"
elif position == 1:
    if edge < -0.02 or r > 80:
        signal = "FLAT"
elif position == -1:
    if edge > 0.02 or r < 20:
        signal = "FLAT"
'''


def build_p1() -> str:
    # The prompt's design: session-filtered RSI(14)+Bollinger mean reversion with
    # VWAP confirmation, range filter, fixed TP via the engine, and prop risk rules.
    return '''
can_enter = (7 <= hour < 17)
overnight = hour >= 18 or hour < 7
adx_v = adx(14)
ranging = adx_v < 25
u, mid, l = bollinger(20, 2.0)
rsi14 = rsi(14)
a = atr(14)
vw = vwap(20)

TARGET = 8.0
halt = day_pnl_pct <= -3.5 or total_pnl_pct <= -6.0 or dd_from_peak_pct >= 8.0
base = 1.5
if dd_from_peak_pct >= 6.0:
    base = base * 0.5
if day_pnl_pct >= 0.25 * TARGET:
    base = base * 0.5
if consec_losses >= 2:
    base = base * 0.5
risk = round(max(0.25, min(base, 1.5)), 2)

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0:
    if can_enter and ranging:
        if rsi14 < 30 and close <= l and close < vw:
            signal = "BUY"
        elif rsi14 > 70 and close >= u and close > vw:
            signal = "SELL"
elif overnight:
    signal = "FLAT"
'''


def build_p2() -> str:
    # p1 + the natural MR exit (revert to the Bollinger mean) and more trades.
    return '''
can_enter = (7 <= hour < 17)
overnight = hour >= 18 or hour < 7
adx_v = adx(14)
ranging = adx_v < 28
u, mid, l = bollinger(20, 2.0)
rsi14 = rsi(14)

TARGET = 8.0
halt = day_pnl_pct <= -3.5 or total_pnl_pct <= -6.0 or dd_from_peak_pct >= 8.0
base = 1.5
if dd_from_peak_pct >= 6.0:
    base = base * 0.5
if day_pnl_pct >= 0.25 * TARGET:
    base = base * 0.5
if consec_losses >= 2:
    base = base * 0.5
risk = round(max(0.25, min(base, 1.5)), 2)

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0:
    if can_enter and ranging:
        if rsi14 < 35 and close <= l:
            signal = "BUY"
        elif rsi14 > 65 and close >= u:
            signal = "SELL"
elif position == 1:
    if close >= mid or overnight:
        signal = "FLAT"
elif position == -1:
    if close <= mid or overnight:
        signal = "FLAT"
'''


def build_s5() -> str:
    # markov_trend_swing (s4) scaled for HIGHER GROWTH: risk to 2.0%, daily stop
    # -2.5% so the worst day stays < 5%; total stop -6%. Scaling a REAL edge.
    return '''
mk = markov(20, band=0.5, window=400)
edge = mk.edge
e200 = ema(200)
r = rsi(2)
up = edge > 0.06 and close > e200
dn = edge < -0.06 and close < e200

halt = total_pnl_pct <= -6.0
day_locked = day_pnl_pct <= -2.5

risk = round(max(0.75, min(0.9 + abs(edge) * 1.5, 2.0)), 2)

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if up and r < 35:
        signal = "BUY"
    elif dn and r > 65:
        signal = "SELL"
elif position == 1:
    if edge < -0.02 or r > 80:
        signal = "FLAT"
elif position == -1:
    if edge > 0.02 or r < 20:
        signal = "FLAT"
'''


def build_t1() -> str:
    # Trend-RIDER for higher growth: enters on BREAKOUTS (catches grind-ups with no
    # dips) or dips, in a markov up/down regime; rides with a far target + wide stop
    # and exits on a trend break (close vs EMA20) or regime flip. Lets winners run.
    return '''
mk = markov(20, band=0.5, window=400)
edge = mk.edge
e200 = ema(200)
e20 = ema(20)
hh = highest(20)
ll = lowest(20)
r = rsi(2)
up = edge > 0.05 and close > e200
dn = edge < -0.05 and close < e200

halt = total_pnl_pct <= -6.0
day_locked = day_pnl_pct <= -2.5
risk = round(max(0.5, min(0.8 + abs(edge) * 1.4, 2.0)), 2)

stop_mult = 2.0     # wider initial stop (trend room)
target_rr = 8.0     # far target -> ride the winner; exit is trend-break/regime-flip

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if up and (close > hh.prev or r < 30):
        signal = "BUY"
    elif dn and (close < ll.prev or r > 70):
        signal = "SELL"
elif position == 1:
    if edge < -0.02 or close < e20:
        signal = "FLAT"
elif position == -1:
    if edge > 0.02 or close > e20:
        signal = "FLAT"
'''


def build_t3() -> str:
    # t1 refined: BREAKOUTS only in a STRONG regime (edge>0.12) to cut whipsaw;
    # dips in any up/down regime. Rides with far target + EMA20 trend-break exit.
    return '''
mk = markov(20, band=0.5, window=400)
edge = mk.edge
e200 = ema(200)
e20 = ema(20)
hh = highest(20)
ll = lowest(20)
r = rsi(2)
up = edge > 0.05 and close > e200
dn = edge < -0.05 and close < e200
strong_up = edge > 0.12 and close > e200
strong_dn = edge < -0.12 and close < e200

halt = total_pnl_pct <= -6.0
day_locked = day_pnl_pct <= -2.5
risk = round(max(0.5, min(0.8 + abs(edge) * 1.4, 2.0)), 2)

stop_mult = 2.0
target_rr = 8.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if (strong_up and close > hh.prev) or (up and r < 25):
        signal = "BUY"
    elif (strong_dn and close < ll.prev) or (dn and r > 75):
        signal = "SELL"
elif position == 1:
    if edge < -0.02 or close < e20:
        signal = "FLAT"
elif position == -1:
    if edge > 0.02 or close > e20:
        signal = "FLAT"
'''


def build_t2() -> str:
    # Swing+ HIGH-QUALITY dip entries, but LET WINNERS RUN: far target + EMA20
    # trend-break trailing exit (no RSI>80 cap). Bigger wins in trends = growth.
    return '''
mk = markov(20, band=0.5, window=400)
edge = mk.edge
e200 = ema(200)
e20 = ema(20)
r = rsi(2)
up = edge > 0.06 and close > e200
dn = edge < -0.06 and close < e200

halt = total_pnl_pct <= -6.0
day_locked = day_pnl_pct <= -2.5
risk = round(max(0.75, min(0.9 + abs(edge) * 1.5, 2.0)), 2)

stop_mult = 1.5
target_rr = 8.0     # far target -> ride; exit is regime flip or EMA20 trend break

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if up and r < 35:
        signal = "BUY"
    elif dn and r > 65:
        signal = "SELL"
elif position == 1:
    if edge < -0.02 or close < e20:
        signal = "FLAT"
elif position == -1:
    if edge > 0.02 or close > e20:
        signal = "FLAT"
'''


def build_a1() -> str:
    # Riptide v2 ADAPTIVE: markov regime switches the trading STYLE -
    #  - strong up/down trend  -> MOMENTUM (breakout, ride) — catches fast moves
    #  - trend + not flipping   -> MEAN-REVERSION dip/rip (the Riptide edge)
    #  - regime flipping against a dip -> stand aside (avoids the falling knife)
    return '''
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

day_locked = day_pnl_pct <= -3.0
mult = 0.5 if dd_from_peak_pct >= 5.0 else 1.0

signal = "HOLD"
if position == 0 and not day_locked:
    if strong_up and close > hh.prev:
        risk = round(min(1.5 * mult, 2.0), 2)
        signal = "BUY"
    elif strong_dn and close < ll.prev:
        risk = round(min(1.5 * mult, 2.0), 2)
        signal = "SELL"
    elif trend_up and edge > -0.05 and r < 15:
        risk = round(min((1.2 + (15 - r) * 0.08) * mult, 2.0), 2)
        signal = "BUY"
    elif trend_dn and edge < 0.05 and r > 85:
        risk = round(min((1.2 + (r - 85) * 0.08) * mult, 2.0), 2)
        signal = "SELL"
elif position == 1:
    if strong_up:
        if close < s20 or edge < -0.05:
            signal = "FLAT"
    elif r > 65 or close > s5 or bars_held > 10:
        signal = "FLAT"
elif position == -1:
    if strong_dn:
        if close > s20 or edge > 0.05:
            signal = "FLAT"
    elif r < 35 or close < s5 or bars_held > 10:
        signal = "FLAT"
'''


def build_a2() -> str:
    # a1 refined: breakout (momentum) in ANY confirmed trend (not just strong-
    # markov) so it actually trades grind-ups/downs; looser MR dip (r<20) still
    # blocked when the regime flips against it. Ride to an EMA20 break.
    return '''
mk = markov(20, band=0.5, window=400)
edge = mk.edge
s200 = sma(200)
s50 = sma(50)
s20 = sma(20)
adx_v = adx(14)
r = rsi(2)
hh = highest(20)
ll = lowest(20)

trend_up = close > s200 and s50 > s200
trend_dn = close < s200 and s50 < s200

day_locked = day_pnl_pct <= -3.0
mult = 0.5 if dd_from_peak_pct >= 5.0 else 1.0

signal = "HOLD"
if position == 0 and not day_locked:
    if trend_up and close > hh.prev:
        risk = round(min(1.5 * mult, 2.0), 2)
        signal = "BUY"
    elif trend_dn and close < ll.prev:
        risk = round(min(1.5 * mult, 2.0), 2)
        signal = "SELL"
    elif trend_up and edge > -0.05 and r < 20:
        risk = round(min((1.0 + (20 - r) * 0.05) * mult, 2.0), 2)
        signal = "BUY"
    elif trend_dn and edge < 0.05 and r > 80:
        risk = round(min((1.0 + (r - 80) * 0.05) * mult, 2.0), 2)
        signal = "SELL"
elif position == 1:
    if close < s20 or r > 70 or bars_held > 15:
        signal = "FLAT"
elif position == -1:
    if close > s20 or r < 30 or bars_held > 15:
        signal = "FLAT"
'''


def build_tf() -> str:
    # Turtle / time-series-momentum trend-follower (the real CTA edge). 20-day
    # breakout entry (both directions -> catches up AND down trends), 10-day
    # opposite-extreme TRAILING exit so winners run for weeks (R:R naturally > 2),
    # wide ATR stop backstop. target_rr far so the trail manages the exit.
    return '''
hh20 = highest(20)
ll20 = lowest(20)
hh10 = highest(10)
ll10 = lowest(10)
a = atr(14)

day_locked = day_pnl_pct <= -4.0
mult = 0.5 if dd_from_peak_pct >= 6.0 else 1.0

stop_mult = 2.5
target_rr = 20.0
risk = round(1.5 * mult, 2)

signal = "HOLD"
if position == 0 and not day_locked:
    if close > hh20.prev:
        signal = "BUY"
    elif close < ll20.prev:
        signal = "SELL"
elif position == 1:
    if close < ll10.prev:
        signal = "FLAT"
elif position == -1:
    if close > hh10.prev:
        signal = "FLAT"
'''


def build_tf3() -> str:
    # tf2 at balanced 1.5% risk with TIERED drawdown-throttle (halve at 5%,
    # quarter at 7.5%) so total DD self-limits well inside FTMO's 10%.
    return '''
hh40 = highest(40)
ll40 = lowest(40)
hh20 = highest(20)
ll20 = lowest(20)

day_locked = day_pnl_pct <= -4.0
mult = 1.0
if dd_from_peak_pct >= 7.5:
    mult = 0.25
elif dd_from_peak_pct >= 5.0:
    mult = 0.5

stop_mult = 3.0
target_rr = 30.0
risk = round(1.5 * mult, 2)

signal = "HOLD"
if position == 0 and not day_locked:
    if close > hh40.prev:
        signal = "BUY"
    elif close < ll40.prev:
        signal = "SELL"
elif position == 1:
    if close < ll20.prev:
        signal = "FLAT"
elif position == -1:
    if close > hh20.prev:
        signal = "FLAT"
'''


def build_tf2() -> str:
    # SLOWER trend system for higher R:R + lower DD: 40-day breakout entry,
    # 20-day trailing exit (rides major trends far), 3-ATR stop, 1% risk.
    return '''
hh40 = highest(40)
ll40 = lowest(40)
hh20 = highest(20)
ll20 = lowest(20)

day_locked = day_pnl_pct <= -4.0
mult = 0.5 if dd_from_peak_pct >= 6.0 else 1.0

stop_mult = 3.0
target_rr = 30.0
risk = round(1.0 * mult, 2)

signal = "HOLD"
if position == 0 and not day_locked:
    if close > hh40.prev:
        signal = "BUY"
    elif close < ll40.prev:
        signal = "SELL"
elif position == 1:
    if close < ll20.prev:
        signal = "FLAT"
elif position == -1:
    if close > hh20.prev:
        signal = "FLAT"
'''


BUILDS = {"v1": build_v1, "v2": build_v2, "v3": build_v3,
          "v4": build_v4, "v5": build_v5, "v6": build_v6, "v7": build_v7,
          "v2a": build_v2a, "v2b": build_v2b, "v2c": build_v2c, "m1": build_m1,
          "s1": build_s1, "s2": build_s2, "s3": build_s3, "s4": build_s4,
          "p1": build_p1, "p2": build_p2, "s5": build_s5, "t1": build_t1,
          "t2": build_t2, "t3": build_t3, "a1": build_a1, "a2": build_a2,
          "tf": build_tf, "tf2": build_tf2, "tf3": build_tf3}

if __name__ == "__main__":
    ver = sys.argv[1] if len(sys.argv) > 1 else "v7"
    which = sys.argv[2] if len(sys.argv) > 2 else "us500"
    code = BUILDS[ver]()
    if which in ("us500", "all"):
        show(ver, code, US500_5M, "US500", 5)
    if which in ("climate", "all"):
        show(ver, code, US500_CLIMATE_60M, "US500", 60)
    if which in ("eur", "all"):
        show(ver, code, EUR_5M, "EURUSD", 5)
    if which in ("eurclim", "all"):
        show(ver, code, EUR_CLIMATE_60M, "EURUSD", 60)
    if which == "deep":
        show(ver, code, [("EURUSD all", None, None)], "EURUSD", 5)
        show(ver, code, [("BTC all", None, None)], "BTCUSD", 5)
    if which == "deep5":
        show(ver, code, EUR_DEEP, "EURUSD", 5)
    if which == "deep15":
        show(ver, code, EUR_DEEP, "EURUSD", 15)
    if which == "deep60":
        show(ver, code, EUR_DEEP, "EURUSD", 60)
    if which == "eurdaily":
        show(ver, code, DAILY, "EURUSD", 1440)
    if which == "trend":
        tw = [("ALL", None, None), ("2017-2019", "2017-01-01", "2020-01-01"),
              ("2020-2022", "2020-01-01", "2023-01-01"), ("2023-2026", "2023-01-01", None)]
        for k in ("BTCUSD", "NAS100", "XAUUSD"):
            show(ver, code, tw, k, 1440)
    if which == "usdaily":
        show(ver, code, DAILY, "US500", 1440)
    if which == "usdailyx":
        show(ver, code, DAILY + [
            ("2026", "2026-01-01", None),
            ("2026 MarJun", "2026-03-01", None),
        ], "US500", 1440)
    if which in ("us60", "us60x", "nas60x"):
        wins = US_DEEP if which == "us60" else (US_DEEP + [
            ("2026Q1", "2026-01-01", "2026-04-01"),
            ("2026 AprJun", "2026-04-01", None),
        ])
        show(ver, code, wins, "NAS100" if which == "nas60x" else "US500", 60)
    if which == "us15":
        show(ver, code, US_DEEP, "US500", 15)
    if which == "deepcmp":
        # v1 (shipped markov_scalper == v3) vs v2 (v2c) on deep 5m EUR/USD climates
        deep = [
            ("2023H1", "2023-01-01", "2023-07-01"),
            ("2023H2", "2023-07-01", "2024-01-01"),
            ("2024H1", "2024-01-01", "2024-07-01"),
            ("2024H2", "2024-07-01", "2025-01-01"),
            ("2025H1", "2025-01-01", "2025-07-01"),
            ("2025H2", "2025-07-01", "2026-01-01"),
            ("2026", "2026-01-01", None),
        ]
        show("v1 (current)", build_v3(), deep, "EURUSD", 5)
        show("v2 (v2c)", build_v2c(), deep, "EURUSD", 5)
