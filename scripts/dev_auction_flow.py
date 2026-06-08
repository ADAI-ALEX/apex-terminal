"""Dev-only iterative harness for the **Auction Flow** AMT scalper.

Loads the local intraday series (real volume), slices by DATE WINDOW (walk-forward
across real climates), runs the candidate snippet through the backtest engine, and
reports the prop-firm risk geometry the two source videos care about:

  * win% / R:R / break-even-win% — the convex-payoff geometry (video #1): a high
    win rate with a modest R:R clears the break-even line with room to spare.
  * daily / total drawdown — the FTMO hard limits (must stay < 5% / < 10%).
  * R^2 linearity of the equity curve — smoothness (low variance = high pass rate).
  * Monte-Carlo P(+10% before -10%) — the actual challenge-pass probability.

The candidate code is read straight from the strategy FILE, so you iterate by
editing ``apex/strategies/custom/auction_flow.py`` and re-running this.

Run:  venv/Scripts/python.exe scripts/dev_auction_flow.py [nas100|us500|both]
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

STRATEGY_FILE = Path(__file__).resolve().parents[1] / "apex" / "strategies" / "custom" / "auction_flow.py"

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


# Realistic round-trip cost (spread+commission) in PRICE units, raw/prop account.
_COST = {"US500": 0.5, "NAS100": 2.0, "EURUSD": 0.00008}


def run(code: str, key: str, tf_min: int, start=None, end=None, mc_runs: int = 400,
        total_limit_pct: float = 9.0) -> dict:
    tf = dataset.suffix_for(tf_min)
    s = full(key, tf)
    cs, exo = _slice(s, start, end)
    if len(cs) < 150:
        return {"error": "too few bars (%d)" % len(cs)}
    st = get_settings()
    r = run_backtest(
        cs, market_for(key), starting_equity=100_000.0,
        risk_pct=st.risk.max_risk_per_trade_pct, atr_stop_mult=st.risk.atr_stop_multiplier,
        params=st.strategy, mc_runs=mc_runs, target_pct=10.0, total_limit_pct=total_limit_pct,
        rr=st.risk.default_rr, strategy={"name": "af", "kind": "custom", "code": code},
        exo=exo, cost_points=_COST.get(key, 0.5),
    )
    d = r.to_dict()
    d["lin"] = linearity(d["equity_curve"])
    d["bars"] = len(cs)
    # Window length in months (for Return/Month normalisation across timeframes).
    d["months"] = max(0.5, (cs[-1].time - cs[0].time).days / 30.44)
    return d


HDR = "%-20s %5s %6s %5s %5s %5s %5s %8s %6s %6s %5s %6s %6s" % (
    "window", "bars", "trades", "win%", "PF", "RR", "BEwn", "ret%", "dDD%", "tDD%",
    "R2", "MCps", "MCbr")


def show(label: str, code: str, windows, key, tf_min=60) -> None:
    print("\n=== %s — %s %dm ===\n%s" % (label, key, tf_min, HDR))
    for nm, a, b in windows:
        d = run(code, key, tf_min, a, b)
        if d.get("error"):
            print("%-20s  %s" % (nm, d["error"]))
            continue
        mc = d["monte_carlo"]
        rr = d["avg_rr"]
        bewin = 100.0 / (1.0 + rr) if rr > 0 else 0.0   # break-even win% for this R:R
        print("%-20s %5d %6d %5.1f %5.2f %5.2f %5.1f %8.2f %6.2f %6.2f %5.2f %6s %6s" % (
            nm, d["bars"], d["trades"], d["win_rate"], d["profit_factor"], rr, bewin,
            d["total_return_pct"], d["max_daily_dd_pct"], d["max_total_dd_pct"],
            d["lin"], mc.get("pass_prob_pct", "-"), mc.get("breach_prob_pct", "-")))


# Half-year walk-forward windows across the seeded 60m history (2023-01 .. 2026-06).
HALVES = [
    ("ALL 2023..2026", None, None),
    ("2023 H1", "2023-01-01", "2023-07-01"),
    ("2023 H2", "2023-07-01", "2024-01-01"),
    ("2024 H1", "2024-01-01", "2024-07-01"),
    ("2024 H2", "2024-07-01", "2025-01-01"),
    ("2025 H1", "2025-01-01", "2025-07-01"),
    ("2025 H2", "2025-07-01", "2026-01-01"),
    ("2026 H1", "2026-01-01", "2026-07-01"),
]


import re  # noqa: E402


def _set(code: str, name: str, value) -> str:
    return re.sub(rf"^{name} = .*?(\s+#|$)", f"{name} = {value}\\1", code, count=1, flags=re.M)


def sweep() -> None:
    """Grid-search the entry/exit geometry on the full window for both indices.

    Prints each config AS it completes (monitorable) and uses a light Monte Carlo.
    """
    base = STRATEGY_FILE.read_text(encoding="utf-8")
    grid = []
    for stop in (1.6, 2.2, 3.0):
        for rr in (0.4, 0.7, 1.0):
            for ts in (6, 10):
                grid.append((stop, rr, ts))
    hdr = "%-20s %6s %6s %5s %5s %6s %6s %6s %6s %6s %6s" % (
        "stop/rr/time", "NASret", "USret", "NASwin", "USwin", "NASpf", "USpf",
        "NASmc", "USmc", "NtDD", "UtDD")
    print(hdr, flush=True)
    for stop, rr, ts in grid:
        code = _set(_set(_set(base, "MR_STOP", stop), "MR_RR", rr), "TIME_STOP", ts)
        nas = run(code, "NAS100", 60, mc_runs=120)
        us = run(code, "US500", 60, mc_runs=120)
        if nas.get("error") or us.get("error"):
            print("%-20s  ERROR" % f"s{stop} rr{rr} t{ts}", flush=True)
            continue
        print("%-20s %6.2f %6.2f %5.1f %5.1f %6.2f %6.2f %6s %6s %6.2f %6.2f" % (
            f"s{stop} rr{rr} t{ts}", nas["total_return_pct"], us["total_return_pct"],
            nas["win_rate"], us["win_rate"], nas["profit_factor"], us["profit_factor"],
            nas["monte_carlo"].get("pass_prob_pct", "-"), us["monte_carlo"].get("pass_prob_pct", "-"),
            nas["max_total_dd_pct"], us["max_total_dd_pct"]), flush=True)


V1_FILE = STRATEGY_FILE
V2_FILE = STRATEGY_FILE.parent / "auction_flow_v2.py"
V3_FILE = STRATEGY_FILE.parent / "auction_flow_v3.py"
V4_FILE = STRATEGY_FILE.parent / "auction_flow_v4.py"
V5_FILE = STRATEGY_FILE.parent / "auction_flow_v5.py"
V5_1_FILE = STRATEGY_FILE.parent / "auction_flow_v5_1_hybrid.py"
V5_2_FILE = STRATEGY_FILE.parent / "auction_flow_v5_2_scaled.py"
V6_A_FILE = STRATEGY_FILE.parent / "auction_flow_v6_0_a_base.py"
V6_B_FILE = STRATEGY_FILE.parent / "auction_flow_v6_0_b_hybrid.py"
V6_1_FILE = STRATEGY_FILE.parent / "auction_flow_v6_1_mtf.py"
V6_2_FILE = STRATEGY_FILE.parent / "auction_flow_v6_2_optimized.py"


def _row15(label: str, path, key: str, mc: int) -> dict | None:
    r = run(path.read_text(encoding="utf-8"), key, 15, mc_runs=mc, total_limit_pct=9.0)
    if r.get("error"):
        print("%-30s  %s" % (label, r["error"]))
        return None
    rpm = r["total_return_pct"] / r["months"]
    mcp = r.get("monte_carlo", {}).get("pass_prob_pct", "-")
    print("%-30s %8.2f %8.3f %7d %6.1f %6.2f %8.2f %8.2f %8.3f %7s" % (
        label, r["total_return_pct"], rpm, r["trades"], r["win_rate"], r["profit_factor"],
        r["max_daily_dd_pct"], r["max_total_dd_pct"], r["expectancy_pct"], mcp), flush=True)
    return r


def compare15(key: str = "US500", mc: int = 200) -> None:
    """Phase-3: V6.0.a / V6.0.b / V6.1 / V6.2 on the full (deep) 15M set (costs ON).

    MC pass is measured against the 9.0% internal total-DD stop; Return/Month
    normalises across the different history lengths."""
    s = full(key, "15m")
    cs = s.candles
    span = f"{cs[0].time.isoformat()[:10]} -> {cs[-1].time.isoformat()[:10]}"
    months = (cs[-1].time - cs[0].time).days / 30.44
    print(f"\n=== V6 family — {key} 15M, {len(cs)} bars ({span}, {months:.0f}mo), costs ON ===")
    print("%-30s %8s %8s %7s %6s %6s %8s %8s %8s %7s" % (
        "strategy", "return%", "ret/mo", "trades", "win%", "PF", "maxDayDD",
        "maxTotDD", "exp/trd", "MC9%"))
    for label, path in (("V6.0.a-Base (100% at POC)", V6_A_FILE),
                        ("V6.0.b-Hybrid (gated runner)", V6_B_FILE),
                        ("V6.1-MTF (anchored)", V6_1_FILE),
                        ("V6.2-Optimized (deep scale)", V6_2_FILE)):
        if path.exists():
            _row15(label, path, key, mc)


def matrix(key: str = "US500") -> None:
    """Phase-3 grand matrix: V4 & V5.2 (1H, last 10k bars) vs the V6 family (deep
    15M), MC pass measured against the 9.0% internal total-DD stop, plus a
    Return/Month normaliser across the different history lengths. Costs ON."""
    st = get_settings()

    def _run_1h(code: str) -> dict:
        s = full(key, "60m")
        cs = s.candles[-10000:]
        exo = {n: v[-10000:] for n, v in s.exo.items()}
        r = run_backtest(
            cs, market_for(key), starting_equity=100_000.0,
            risk_pct=st.risk.max_risk_per_trade_pct, atr_stop_mult=st.risk.atr_stop_multiplier,
            params=st.strategy, mc_runs=300, target_pct=10.0, total_limit_pct=9.0,
            rr=st.risk.default_rr, strategy={"name": "m", "kind": "custom", "code": code},
            exo=exo, cost_points=_COST.get(key, 0.5),
        ).to_dict()
        r["months"] = (cs[-1].time - cs[0].time).days / 30.44
        return r

    rows = [
        ("V4 (1H Base)", _run_1h(V4_FILE.read_text(encoding="utf-8"))),
        ("V5.2 (1H Scaled Peak)", _run_1h(V5_2_FILE.read_text(encoding="utf-8"))),
        ("V6.0.a (15M Base)", run(V6_A_FILE.read_text(encoding="utf-8"), key, 15, mc_runs=150, total_limit_pct=9.0)),
        ("V6.0.b (15M Hybrid)", run(V6_B_FILE.read_text(encoding="utf-8"), key, 15, mc_runs=150, total_limit_pct=9.0)),
        ("V6.1 (15M MTF)", run(V6_1_FILE.read_text(encoding="utf-8"), key, 15, mc_runs=150, total_limit_pct=9.0)),
        ("V6.2 (15M Deep)", run(V6_2_FILE.read_text(encoding="utf-8"), key, 15, mc_runs=150, total_limit_pct=9.0)),
    ]
    print("\n=== GRAND MATRIX (%s, costs ON, MC vs 9%% total-DD stop) ===" % key)
    print("%-22s %8s %7s %7s %6s %6s %8s %8s %8s %6s" % (
        "strategy", "return%", "ret/mo", "trades", "win%", "PF", "maxDayDD",
        "maxTotDD", "exp/trd", "MC9%"))
    for label, r in rows:
        if r.get("error"):
            print("%-22s  %s" % (label, r["error"]))
            continue
        rpm = r["total_return_pct"] / r["months"]
        mcp = r.get("monte_carlo", {}).get("pass_prob_pct", "-")
        print("%-22s %8.2f %7.3f %7d %6.1f %6.2f %8.2f %8.2f %8.3f %6s" % (
            label, r["total_return_pct"], rpm, r["trades"], r["win_rate"],
            r["profit_factor"], r["max_daily_dd_pct"], r["max_total_dd_pct"],
            r["expectancy_pct"], mcp), flush=True)


def compare(key: str = "US500", bars: int = 10000) -> None:
    """Side-by-side V1..V5.2 over the most recent ``bars`` candles (costs ON)."""
    s = full(key, "60m")
    cs = s.candles[-bars:]
    exo = {n: v[-bars:] for n, v in s.exo.items()}
    span = f"{cs[0].time.isoformat()[:10]} -> {cs[-1].time.isoformat()[:10]}"
    print(f"\n=== V1..V5.2 — {key} 60m, last {len(cs)} bars ({span}), costs ON ===")
    print("%-28s %8s %7s %6s %6s %6s %8s %8s" % (
        "strategy", "return%", "trades", "win%", "avgRR", "PF", "maxDayDD", "maxTotDD"))
    st = get_settings()
    variants = (("Auction Flow V1", V1_FILE),
                ("Auction Flow V2 (Challenge)", V2_FILE),
                ("Auction Flow V3 (Max Util)", V3_FILE),
                ("Auction Flow V4 (Max Risk)", V4_FILE),
                ("Auction Flow V5 (Asymmetric)", V5_FILE),
                ("Auction Flow V5.1 (Hybrid)", V5_1_FILE),
                ("Auction Flow V5.2 (Scaled)", V5_2_FILE))
    for label, path in variants:
        code = path.read_text(encoding="utf-8")
        r = run_backtest(
            cs, market_for(key), starting_equity=100_000.0,
            risk_pct=st.risk.max_risk_per_trade_pct, atr_stop_mult=st.risk.atr_stop_multiplier,
            params=st.strategy, mc_runs=400, target_pct=10.0, total_limit_pct=10.0,
            rr=st.risk.default_rr, strategy={"name": label, "kind": "custom", "code": code},
            exo=exo, cost_points=_COST.get(key, 0.5),
        ).to_dict()
        # Realised R:R = avg win / avg loss (payoff ratio) = PF * (losses/wins).
        wr = r["win_rate"] / 100.0
        pf = r["profit_factor"]
        avg_rr = round(pf * (1.0 - wr) / wr, 2) if 0.0 < wr < 1.0 else 0.0
        print("%-28s %8.2f %7d %6.1f %6.2f %6.2f %8.2f %8.2f" % (
            label, r["total_return_pct"], r["trades"], r["win_rate"], avg_rr, pf,
            r["max_daily_dd_pct"], r["max_total_dd_pct"]))
        mc = r.get("monte_carlo", {})
        print("    MC P(+10%% before -10%%): %s%%   breach: %s%%   expectancy/trade: %s%%" % (
            mc.get("pass_prob_pct", "-"), mc.get("breach_prob_pct", "-"), r["expectancy_pct"]))


def main() -> None:
    which = (sys.argv[1].lower() if len(sys.argv) > 1 else "both")
    if which == "sweep":
        sweep()
        return
    if which == "compare":
        compare()
        return
    if which == "compare15":
        compare15()
        return
    if which == "matrix":
        matrix()
        return
    code = STRATEGY_FILE.read_text(encoding="utf-8")
    keys = {"nas100": ["NAS100"], "us500": ["US500"], "both": ["NAS100", "US500"]}.get(which, ["NAS100", "US500"])
    for key in keys:
        show("Auction Flow", code, HALVES, key, tf_min=60)


if __name__ == "__main__":
    main()
