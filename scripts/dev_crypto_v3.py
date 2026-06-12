"""Dev-only Phase-5.3 PORTFOLIO harness — blends per-instrument engines into one
account and measures the metrics that matter at the account level.

The production stack runs ONE snippet per (instrument, timeframe). A higher
trade frequency therefore comes from an ENSEMBLE of engines on separate
instruments/timeframes sharing the account. This harness:

  * runs each component through the production backtest engine (costs ON),
    with full-resolution equity curves (the 600-point downsample is patched
    out, dev-only)
  * merges the component curves into a single portfolio equity stream
    (eq_pf = 100k + sum of component P&L, last-value carry across timestamps)
  * reports portfolio monthly return, MAX DAILY floating DD (UTC days, the
    FTMO measure), max total floating DD, trade count, and a Monte-Carlo
    bootstrap of the combined chronological trade stream vs +10%/-9%.

Caveat (documented, conservative direction unknown): each component's internal
risk throttles see its OWN equity, not the portfolio's. Live, the throttles
would act on shared account state and couple the books slightly.

Run:  venv/Scripts/python.exe scripts/dev_crypto_v3.py <port> [full|one] [scale notes like a=2.8 b=1.1 c=1.1]
"""
from __future__ import annotations

import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

logger.remove()

import apex.backtest.engine as eng  # noqa: E402

eng._downsample = lambda pts, limit: pts  # dev-only: keep full equity curves

from apex.backtest.engine import run_backtest  # noqa: E402
from apex.backtest.runner import LOCAL_BACKTEST_MARKETS  # noqa: E402
from apex.config import MARKETS, get_settings  # noqa: E402
from dev_crypto_v2 import HALVES, ONE, load_tf, _slice  # noqa: E402

COST_PCT = 0.12
ROOT = Path(__file__).resolve().parents[1]
CUSTOM = ROOT / "apex" / "strategies" / "custom"


def _code(fname: str, base_risk: float | None = None) -> str:
    code = (CUSTOM / fname).read_text(encoding="utf-8")
    if base_risk is not None:
        code, n = re.subn(r"(?m)^risk = [\d.]+$", f"risk = {base_risk}", code)
        assert n == 1, f"{fname}: expected exactly one 'risk = X' line, found {n}"
    return code


def run_component(code: str, key: str, tf_min: int, start, end, cost=COST_PCT) -> dict | None:
    candles, exo = load_tf(key, tf_min)
    cs, ex = _slice(candles, exo, start, end)
    if len(cs) < (100 if tf_min >= 1440 else 300):   # daily legs: half-year ~159 bars
        return None
    st = get_settings()
    # Cost model must match the instrument: percent-of-notional for crypto
    # perps (price spans 10x across the data), fixed POINTS for index CFDs
    # (US500 ~0.5pt RT — charging 0.12% of a 6000 notional would be a 14x
    # overcharge that falsely kills any 1R scalper).
    is_crypto = key in ("BTCUSD", "ETHUSD")
    r = run_backtest(
        cs, MARKETS.get(key) or LOCAL_BACKTEST_MARKETS[key], starting_equity=100_000.0,
        risk_pct=st.risk.max_risk_per_trade_pct, atr_stop_mult=st.risk.atr_stop_multiplier,
        params=st.strategy, mc_runs=0, rr=st.risk.default_rr,
        strategy={"name": "pf", "kind": "custom", "code": code}, exo=ex,
        cost_pct=cost if is_crypto else 0.0,
        cost_points=0.0 if is_crypto else eng.default_cost_points(
            MARKETS.get(key) or LOCAL_BACKTEST_MARKETS[key]),
    )
    d = r.to_dict()
    return d


def merge(curves: list[list[dict]]) -> list[tuple[int, float]]:
    """Portfolio equity = 100k + sum of component P&L, last-value carried."""
    times = sorted({p["time"] for c in curves for p in c})
    idx = [0] * len(curves)
    last = [100_000.0] * len(curves)
    out = []
    for t in times:
        for ci, c in enumerate(curves):
            while idx[ci] < len(c) and c[idx[ci]]["time"] <= t:
                last[ci] = c[idx[ci]]["equity"]
                idx[ci] += 1
        out.append((t, 100_000.0 + sum(v - 100_000.0 for v in last)))
    return out


def portfolio_metrics(curve: list[tuple[int, float]]) -> dict:
    peak = -1e18
    tdd = 0.0
    day_start: dict[str, float] = {}
    day_min: dict[str, float] = {}
    for t, eq in curve:
        day = datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()
        day_start.setdefault(day, eq)
        day_min[day] = min(day_min.get(day, eq), eq)
        peak = max(peak, eq)
        tdd = max(tdd, 100.0 * (peak - eq) / peak if peak > 0 else 0.0)
    ddd = max((100.0 * (s - day_min[d]) / s for d, s in day_start.items() if s > 0), default=0.0)
    months = (curve[-1][0] - curve[0][0]) / (86400.0 * 30.44) if len(curve) > 1 else 0.0
    ret = 100.0 * (curve[-1][1] - 100_000.0) / 100_000.0
    return {"ret": ret, "months": months, "rpm": ret / months if months else 0.0,
            "ddd": ddd, "tdd": tdd}


def mc(trade_rets: list[float], runs=400, target=10.0, limit=9.0, seed=7) -> dict:
    if len(trade_rets) < 5:
        return {"pass": "-", "breach": "-"}
    rng = random.Random(seed)
    n = len(trade_rets)
    p = b = 0
    for _ in range(runs):
        eq = pk = 0.0
        for _ in range(n):
            eq += rng.choice(trade_rets)
            pk = max(pk, eq)
            if pk - eq >= limit:
                b += 1
                break
            if eq >= target:
                p += 1
                break
    return {"pass": round(100.0 * p / runs, 1), "breach": round(100.0 * b / runs, 1)}


#: Vector-1 probe: macro-gated intraday DIP sub-state (15M). Buys RSI(2)
#: capitulation INSIDE the verified macro-bull regime, flow not hostile,
#: tight 2-ATR stop / 2R target / 32-bar time exit. Fractional risk 0.8%.
DIP15 = '''
a = atr(14)
r = rsi(2)
f = flow_norm(20)
trend = sma(384)

ok = not (isnan(r) or isnan(f) or isnan(trend) or isnan(macro) or isnan(macro_slow))
enter = (ok and macro > 3.0 and macro_slow > 0.0 and close > trend
         and r < 10.0 and f > -0.02)

halt = dd_from_peak_pct >= 7.5 or total_pnl_pct <= -7.0
day_locked = day_pnl_pct <= -2.0 or trades_today >= 6

risk = 0.8
if consec_losses >= 2:
    risk = risk * 0.6
if dd_from_peak_pct >= 3.5:
    risk = risk * 0.5
risk = round(max(0.3, risk), 2)

stop_mult = 2.0
target_rr = 2.0

signal = "HOLD"
if halt:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked:
    if enter:
        signal = "BUY"
elif position == 1:
    if r > 70.0 or bars_held >= 32:
        signal = "FLAT"
'''


#: component = (tag, strategy file, base-risk override (None = as shipped),
#:              instrument, timeframe-minutes)
PORTFOLIOS: dict[str, list[tuple[str, str, float | None, str, int]]] = {
    # A: shipped V2 alone (control at portfolio-metric level)
    "A": [("btc4h", "crypto_state_v2.py", None, "BTCUSD", 240)],
    # AC: V2 + ETH 15M V1 (fills the 4H dead space, separate asset)
    "AC": [("btc4h", "crypto_state_v2.py", None, "BTCUSD", 240),
           ("eth15", "crypto_state_v1.py", None, "ETHUSD", 15)],
    # ABC: + BTC 15M V1 (same asset as the 4H book — correlation risk, measure it)
    "ABC": [("btc4h", "crypto_state_v2.py", None, "BTCUSD", 240),
            ("btc15", "crypto_state_v1.py", None, "BTCUSD", 15),
            ("eth15", "crypto_state_v1.py", None, "ETHUSD", 15)],
    # AV: CROSS-SECTOR — crypto 4H trend + US500 1H auction scalper (V5.2, the
    # shipped index champion). Different asset class, different drawdown clock.
    "AV": [("btc4h", "crypto_state_v2.py", None, "BTCUSD", 240),
           ("us500", "auction_flow_v5_2_scaled.py", None, "US500", 60)],
    # AV1: same blend but the US500 leg at V5.1 sizing (1.2-1.9% band) — V5.2
    # standalone runs tDD 8.85 ("RUNS HOT"); the blend needs its headroom back.
    "AV1": [("btc4h", "crypto_state_v2.py", None, "BTCUSD", 240),
            ("us500", "auction_flow_v5_1_hybrid.py", None, "US500", 60)],
    # G: the validated DAILY gold CTA alone (clean-data turtle, points costs)
    "G": [("gold", "momentum_trend.py", None, "XAUUSD", 1440)],
    # AVG: Phase-5.4 THREE-PILLAR global macro — crypto 4H + index 1H + gold D1
    "AVG": [("btc4h", "crypto_state_v2.py", None, "BTCUSD", 240),
            ("us500", "auction_flow_v5_1_hybrid.py", None, "US500", 60),
            ("gold", "momentum_trend.py", None, "XAUUSD", 1440)],
}


def show_portfolio(tag: str, comps, windows, scales: dict[str, float], cost=COST_PCT) -> None:
    hdr = "%-14s %7s %7s %7s %6s %6s %6s %7s" % (
        "window", "trades", "ret%", "ret/mo", "dDD%", "tDD%", "MC%", "breach%")
    print(f"\n=== portfolio {tag} — scales {scales or 'shipped'} (cost {cost:.2f}% RT) ===")
    for nm, comp_tag, _f, risk, key, tf in [
            (None, c[0], c[1], scales.get(c[0], c[2]), c[3], c[4]) for c in comps]:
        print(f"  {comp_tag}: {key}@{tf}m risk={'shipped' if risk is None else risk}")
    print(hdr)
    for wname, a, b in windows:
        curves, rets_t = [], []
        n_tr = 0
        skip = False
        for ctag, fname, drisk, key, tf in comps:
            risk = scales.get(ctag, drisk)
            d = run_component(_code(fname, risk), key, tf, a, b, cost)
            if d is None:
                skip = True
                break
            curves.append(d["equity_curve"])
            n_tr += d["trades"]
            rets_t += [(t["closed"], t["ret_pct"]) for t in d["trade_log"]
                       if t["reason"] != "SCALE"]
        if skip:
            print("%-14s  too few bars" % wname)
            continue
        pm = portfolio_metrics(merge(curves))
        rets = [r for _, r in sorted(rets_t)]
        m = mc(rets)
        print("%-14s %7d %7.2f %7.2f %6.2f %6.2f %6s %7s" % (
            wname, n_tr, pm["ret"], pm["rpm"], pm["ddd"], pm["tdd"],
            m["pass"], m["breach"]))


def probe_dip() -> None:
    """One decisive FULL-run check of the DIP15 sub-state on both symbols."""
    for key in ("BTCUSD", "ETHUSD"):
        d = run_component(DIP15, key, 15, None, None)
        months = d["bars"] * 15 / (60.0 * 24.0 * 30.44) if d else 0.0
        if d:
            print(f"DIP15 {key}: trades={d['trades']} win={d['win_rate']}% "
                  f"PF={d['profit_factor']} ret={d['total_return_pct']}% "
                  f"({d['total_return_pct']/months:.2f}%/mo) "
                  f"dDD={d['max_daily_dd_pct']} tDD={d['max_total_dd_pct']}")


if __name__ == "__main__":
    args = sys.argv[1:]
    port = args[0] if args else "A"
    which = args[1] if len(args) > 1 else "one"
    if port == "dip":
        probe_dip()
        sys.exit(0)
    scales: dict[str, float] = {}
    cost = COST_PCT
    for a in args[2:]:
        if "=" in a:
            k, v = a.split("=", 1)
            scales[k] = float(v)
        else:
            cost = float(a)
    windows = HALVES if which == "full" else ONE
    show_portfolio(port, PORTFOLIOS[port], windows, scales, cost)
