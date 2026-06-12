"""Dev-only Phase-5.2 harness — crypto state engine moved UP the timeframe ladder.

Extends scripts/dev_crypto_state.py (15M, V1) to 1H and 4H:
  * native 1H runs over the deep Binance perp seeds (BTCUSD/ETHUSD 2020-2026)
  * in-memory 4H resample of the 1H series (OHLC agg, volume+delta summed,
    walk-forward macro/macro_slow take the bucket's LAST value — still strictly
    derived from completed daily closes, so no look-ahead is introduced)
  * a calibration probe (``probe`` mode) measuring the ATR%% -> per-bar return
    sigma ratio per timeframe so momentum z-scores stay correctly normalized
    (V1's 15m constants 6.53/3.27 do NOT transfer across timeframes)
  * candidate v2 snippets: V1-transposed control, wide-ATR-trail trend riders,
    macro-gated turtle breakouts, and risk-curve loosening sweeps

Costs stay percentage-of-notional (0.12%% RT default; stress at 0.18%%).

Run:  venv/Scripts/python.exe scripts/dev_crypto_v2.py <ver> [dev|full|one|eth|eth4|one4|full4|probe] [cost_pct] [risk=X] [trail=Y] [stop=Z]
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

logger.remove()

from apex.backtest import dataset  # noqa: E402
from apex.backtest.engine import run_backtest  # noqa: E402
from apex.backtest.runner import LOCAL_BACKTEST_MARKETS  # noqa: E402
from apex.config import MARKETS, get_settings  # noqa: E402
from apex.models import Candle  # noqa: E402

COST_PCT = 0.12

_CACHE: dict = {}


# ── data: native 1H + in-memory 4H resample ─────────────────────────────────
def load_tf(key: str, tf_min: int):
    """(candles, exo) for ``key`` at 60 or 240 minutes (240 = resampled 1H)."""
    ck = (key, tf_min)
    if ck in _CACHE:
        return _CACHE[ck]
    if tf_min == 240:
        c60, e60 = load_tf(key, 60)
        _CACHE[ck] = _resample(c60, e60, 240)
    else:
        s = dataset.load(key, 0, timeframe=dataset.suffix_for(tf_min))
        _CACHE[ck] = (s.candles, s.exo)
    return _CACHE[ck]


def _resample(candles: list[Candle], exo: dict, tf_min: int):
    """Aggregate 1H bars into ``tf_min`` buckets aligned to UTC midnight."""
    step = tf_min * 60
    out_c: list[Candle] = []
    out_e: dict[str, list[float]] = {k: [] for k in exo}
    bucket = None
    o = h = l = c = v = 0.0
    sums = {k: 0.0 for k in exo}
    lasts = {k: 0.0 for k in exo}

    def _flush(ts):
        out_c.append(Candle(time=datetime.fromtimestamp(ts, tz=timezone.utc),
                            open=o, high=h, low=l, close=c, volume=v))
        for k in exo:
            out_e[k].append(sums[k] if k == "delta" else lasts[k])

    for i, bar in enumerate(candles):
        b = int(bar.time.timestamp()) // step * step
        if bucket is None or b != bucket:
            if bucket is not None:
                _flush(bucket)
            bucket, o, h, l, c, v = b, bar.open, bar.high, bar.low, bar.close, bar.volume
            sums = {k: 0.0 for k in exo}
        else:
            h, l, c, v = max(h, bar.high), min(l, bar.low), bar.close, v + bar.volume
        for k in exo:
            sums[k] += exo[k][i] if exo[k] else 0.0
            lasts[k] = exo[k][i] if exo[k] else 0.0
    if bucket is not None:
        _flush(bucket)
    return out_c, out_e


def _slice(candles, exo, start, end):
    idx = [i for i, c in enumerate(candles)
           if (start is None or c.time.isoformat()[:10] >= start)
           and (end is None or c.time.isoformat()[:10] < end)]
    if not idx:
        return [], {}
    a, b = idx[0], idx[-1] + 1
    return candles[a:b], {n: v[a:b] for n, v in exo.items()}


# ── z-score calibration probe ────────────────────────────────────────────────
def probe(key: str, tf_min: int) -> None:
    """Measure ATR%(14) vs rolling per-bar return sigma; print z divisors.

    z_N = roc(N) / (sigma_bar * sqrt(N)) and sigma_bar ~= atrp / RATIO, so the
    snippet divisor for horizon N is  atrp * (sqrt(N) / RATIO).
    """
    candles, _ = load_tf(key, tf_min)
    closes = [c.close for c in candles]
    n = len(candles)
    trs = [0.0] * n
    for i in range(1, n):
        pc = closes[i - 1]
        trs[i] = max(candles[i].high - candles[i].low,
                     abs(candles[i].high - pc), abs(candles[i].low - pc))
    rets = [100.0 * (closes[i] / closes[i - 1] - 1.0) for i in range(1, n)]
    ratios = []
    atr = sum(trs[1:15]) / 14.0
    win = 500
    s = sum(rets[:win])
    s2 = sum(r * r for r in rets[:win])
    for i in range(15, n - 1):
        atr = (atr * 13 + trs[i]) / 14.0          # Wilder
        if i >= win + 1:
            j = i - 1                              # rets index of current bar
            s += rets[j] - rets[j - win]
            s2 += rets[j] ** 2 - rets[j - win] ** 2
            var = max(1e-12, (s2 - s * s / win) / win)
            sigma = math.sqrt(var)
            atrp = 100.0 * atr / closes[i]
            if sigma > 0:
                ratios.append(atrp / sigma)
    ratios.sort()
    med = ratios[len(ratios) // 2]
    bars_day = 1440 // tf_min
    print(f"{key} {tf_min}m: bars={n} median atrp/sigma RATIO = {med:.3f} "
          f"(p25 {ratios[len(ratios)//4]:.3f}, p75 {ratios[3*len(ratios)//4]:.3f})")
    for label, nb in (("24h", bars_day), ("6h", max(1, bars_day // 4)),
                      ("3d", 3 * bars_day), ("1w", 7 * bars_day)):
        print(f"  z divisor {label} (N={nb}): atrp * {math.sqrt(nb)/med:.3f}")


# ── runner / reporter (same contract as the V1 harness) ─────────────────────
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
    candles, exo = load_tf(key, tf_min)
    cs, ex = _slice(candles, exo, start, end)
    if len(cs) < 300:
        return {"error": "too few bars (%d)" % len(cs)}
    st = get_settings()
    r = run_backtest(
        cs, MARKETS.get(key) or LOCAL_BACKTEST_MARKETS[key], starting_equity=100_000.0,
        risk_pct=st.risk.max_risk_per_trade_pct, atr_stop_mult=st.risk.atr_stop_multiplier,
        params=st.strategy, mc_runs=300, target_pct=10.0, total_limit_pct=9.0,
        rr=st.risk.default_rr, strategy={"name": "cs2", "kind": "custom", "code": code},
        exo=ex, cost_pct=cost_pct,
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


def show(label: str, code: str, windows, key="BTCUSD", tf_min=60, cost_pct=COST_PCT) -> None:
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
DEV = [HALVES[2], HALVES[5], HALVES[9], HALVES[12]]
ONE = [("FULL 2020-26", None, None)]


# ── candidate snippets ───────────────────────────────────────────────────────
# Calibration (probe 2026-06-10): median atrp/sigma RATIO = 1.37 on 1H and
# 1.36 on 4H, near-identical BTC vs ETH -> one constant set serves both.
# divisor(N) = sqrt(N) / RATIO  (z_N = roc(N) / (atrp * divisor))
K = {"1h_24h": 3.58, "1h_6h": 1.79, "4h_24h": 1.80, "4h_3d": 3.12}


def build_h0(risk=1.1, trail=0.0, stop=4.0) -> str:
    # CONTROL: V1 transposed verbatim to 1H. 24h = roc(24), 6h = roc(6),
    # 4-day local trend = sma(96). Same gates, exits, risk curve as V1.
    return f'''
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r24 = roc(24)
r6 = roc(6)
f = flow_norm(20)
trend = sma(96)

z24 = r24 / (atrp * {K["1h_24h"]}) if (not isnan(atrp)) and atrp > 0 else nan
z6 = r6 / (atrp * {K["1h_6h"]}) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z24) or isnan(z6) or isnan(f) or isnan(trend) or isnan(macro) or isnan(macro_slow))
enter = (ok and macro > 3.0 and macro_slow > 0.0 and z24 > 1.0 and z6 > 0.5
         and f > 0.02 and close > trend)
mom_dead = ok and z24 < 0.0

halt = dd_from_peak_pct >= 7.5 or total_pnl_pct <= -7.0
day_locked = day_pnl_pct <= -2.0 or trades_today >= 6

risk = {risk}
if consec_losses >= 4:
    risk = risk * 0.35
elif consec_losses >= 2:
    risk = risk * 0.6
if dd_from_peak_pct >= 5.0:
    risk = risk * 0.35
elif dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.3, risk), 2)

stop_mult = min(5.0, max({stop}, 2.2 / atrp)) if (ok and atrp > 0) else {stop}
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


def build_h1(risk=1.1, trail=8.0, stop=4.0) -> str:
    # TREND RIDER: h0 entries; exit = wide ATR trail (ratcheted in the engine)
    # + far 12R target + macro-death bail. No momentum-death exit — winners
    # ride until the trail or the daily regime takes them out.
    return f'''
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r24 = roc(24)
r6 = roc(6)
f = flow_norm(20)
trend = sma(96)

z24 = r24 / (atrp * {K["1h_24h"]}) if (not isnan(atrp)) and atrp > 0 else nan
z6 = r6 / (atrp * {K["1h_6h"]}) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z24) or isnan(z6) or isnan(f) or isnan(trend) or isnan(macro) or isnan(macro_slow))
enter = (ok and macro > 3.0 and macro_slow > 0.0 and z24 > 1.0 and z6 > 0.5
         and f > 0.02 and close > trend)
regime_dead = ok and (macro < 0.0 or macro_slow < 0.0)

halt = dd_from_peak_pct >= 7.5 or total_pnl_pct <= -7.0
day_locked = day_pnl_pct <= -2.0 or trades_today >= 6

risk = {risk}
if consec_losses >= 4:
    risk = risk * 0.35
elif consec_losses >= 2:
    risk = risk * 0.6
if dd_from_peak_pct >= 5.0:
    risk = risk * 0.35
elif dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.3, risk), 2)

stop_mult = min(5.0, max({stop}, 2.2 / atrp)) if (ok and atrp > 0) else {stop}
target_rr = 12.0
trail_dist = {trail} * a if (a and a > 0) else None

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if regime_dead:
        signal = "FLAT"
'''


def build_h2(risk=1.1, trail=10.0, stop=4.0) -> str:
    # TURTLE-MACRO: 20-day breakout entry (fresh 480-bar high) gated by the
    # macro stack + flow; wide ATR trail; regime-death bail. The CTA classic
    # rebuilt for crypto 1H inside the prop envelope.
    return f'''
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
hh = highest(480)
f = flow_norm(20)

ok = not (isnan(hh) or isnan(f) or isnan(macro) or isnan(macro_slow)) and a and a > 0
enter = (ok and macro > 3.0 and macro_slow > 0.0 and close > hh.prev and f > 0.0)
regime_dead = ok and (macro < 0.0 or macro_slow < 0.0)

halt = dd_from_peak_pct >= 7.5 or total_pnl_pct <= -7.0
day_locked = day_pnl_pct <= -2.0 or trades_today >= 6

risk = {risk}
if consec_losses >= 4:
    risk = risk * 0.35
elif consec_losses >= 2:
    risk = risk * 0.6
if dd_from_peak_pct >= 5.0:
    risk = risk * 0.35
elif dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.3, risk), 2)

stop_mult = min(5.0, max({stop}, 2.2 / atrp)) if (ok and atrp > 0) else {stop}
target_rr = 20.0
trail_dist = {trail} * a if (a and a > 0) else None

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if regime_dead:
        signal = "FLAT"
'''


def build_h3(risk=1.1, trail=6.0, stop=4.0) -> str:
    # 4H STATE: V1 transposed to 4H. 24h = roc(6), 3d = roc(18); local trend
    # sma(24) = 4 days. Run with tf_min=240 modes (one4/full4/eth4).
    return f'''
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r6 = roc(6)
r18 = roc(18)
f = flow_norm(20)
trend = sma(24)

z24 = r6 / (atrp * {K["4h_24h"]}) if (not isnan(atrp)) and atrp > 0 else nan
z3d = r18 / (atrp * {K["4h_3d"]}) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z24) or isnan(z3d) or isnan(f) or isnan(trend) or isnan(macro) or isnan(macro_slow))
enter = (ok and macro > 3.0 and macro_slow > 0.0 and z24 > 1.0 and z3d > 0.5
         and f > 0.02 and close > trend)
mom_dead = ok and z3d < 0.0

halt = dd_from_peak_pct >= 7.5 or total_pnl_pct <= -7.0
day_locked = day_pnl_pct <= -2.0 or trades_today >= 4

risk = {risk}
if consec_losses >= 4:
    risk = risk * 0.35
elif consec_losses >= 2:
    risk = risk * 0.6
if dd_from_peak_pct >= 5.0:
    risk = risk * 0.35
elif dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.3, risk), 2)

stop_mult = min(5.0, max({stop}, 2.2 / atrp)) if (ok and atrp > 0) else {stop}
target_rr = 6.0
trail_dist = {trail} * a if (a and a > 0) else None

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


def build_h4(risk=2.8, z=1.0, z3=0.5, flow=0.02, mac=3.0, stop=4.0, trail=0.0,
             d1=3.5, d2=5.0, m1=0.5, m2=0.35) -> str:
    # h3 with parameterized gates — frequency/robustness sweeps. trail=0 (the
    # momentum-death exit beat every trail width tested on BOTH 1H and 4H).
    # d1/d2 + m1/m2 parameterize the peak-DD throttle tiers for the loosening test.
    return f'''
a = atr(14)
atrp = 100.0 * a / close if (a and a > 0) else nan
r6 = roc(6)
r18 = roc(18)
f = flow_norm(20)
trend = sma(24)

z24 = r6 / (atrp * {K["4h_24h"]}) if (not isnan(atrp)) and atrp > 0 else nan
z3d = r18 / (atrp * {K["4h_3d"]}) if (not isnan(atrp)) and atrp > 0 else nan

ok = not (isnan(z24) or isnan(z3d) or isnan(f) or isnan(trend) or isnan(macro) or isnan(macro_slow))
enter = (ok and macro > {mac} and macro_slow > 0.0 and z24 > {z} and z3d > {z3}
         and f > {flow} and close > trend)
mom_dead = ok and z3d < 0.0

halt = dd_from_peak_pct >= 7.5 or total_pnl_pct <= -7.0
day_locked = day_pnl_pct <= -2.0 or trades_today >= 4

risk = {risk}
if consec_losses >= 4:
    risk = risk * 0.35
elif consec_losses >= 2:
    risk = risk * 0.6
if dd_from_peak_pct >= {d2}:
    risk = risk * {m2}
elif dd_from_peak_pct >= {d1}:
    risk = risk * {m1}
risk = round(max(0.3, risk), 2)

stop_mult = min(5.0, max({stop}, 2.2 / atrp)) if (ok and atrp > 0) else {stop}
target_rr = 6.0
trail_dist = {trail} * a if (a and a > 0) else None

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


BUILDS = {"h0": build_h0, "h1": build_h1, "h2": build_h2, "h3": build_h3,
          "h4": build_h4}

if __name__ == "__main__":
    args = sys.argv[1:]
    ver = args[0] if args else "h0"
    which = args[1] if len(args) > 1 else "dev"
    cost = COST_PCT
    kw: dict = {}
    for a in args[2:]:
        if "=" in a:
            k, v = a.split("=", 1)
            kw[k] = float(v)
        else:
            cost = float(a)

    if which == "probe":
        for tf in (60, 240):
            probe("BTCUSD", tf)
            probe("ETHUSD", tf)
        sys.exit(0)

    code = BUILDS[ver](**kw)
    if which == "dev":
        show(ver, code, DEV, "BTCUSD", 60, cost)
    elif which == "full":
        show(ver, code, HALVES, "BTCUSD", 60, cost)
    elif which == "one":
        show(ver, code, ONE, "BTCUSD", 60, cost)
    elif which == "eth":
        show(ver, code, HALVES, "ETHUSD", 60, cost)
    elif which == "ethone":
        show(ver, code, ONE, "ETHUSD", 60, cost)
    elif which == "full4":
        show(ver, code, HALVES, "BTCUSD", 240, cost)
    elif which == "one4":
        show(ver, code, ONE, "BTCUSD", 240, cost)
    elif which == "eth4":
        show(ver, code, HALVES, "ETHUSD", 240, cost)
