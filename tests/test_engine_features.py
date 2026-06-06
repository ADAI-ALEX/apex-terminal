"""Tests for reusable backtest-engine features (kept after retiring the artifact
strategies): prop-firm risk state, FX min-stop units, hour/VWAP, transaction
costs, and snippet-controlled stop/target overrides."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from apex.backtest.custom_runner import CompiledStrategy, validate_code
from apex.backtest.engine import (
    _min_stop_price,
    cost_points_from_pips,
    default_cost_points,
    run_backtest,
)
from apex.config import MARKETS
from apex.models import Candle


def _candles(n: int = 300, start: float = 5000.0) -> list[Candle]:
    out: list[Candle] = []
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    price = start
    for i in range(n):
        price += math.sin(i / 8.0) * 6.0 + (3.0 if i % 2 else -2.0)
        o = price
        c = price + math.sin(i / 5.0) * 2.0
        out.append(Candle(time=base + timedelta(hours=i), open=o,
                          high=max(o, c) + 4, low=min(o, c) - 4, close=c, volume=1000))
    return out


def test_prop_risk_state_exposed():
    code = (
        "ok = (day_pnl_pct <= 0 or day_pnl_pct >= 0) and consec_losses >= 0 "
        "and consec_wins >= 0 and trades_today >= 0 and dd_from_peak_pct >= 0 "
        "and (total_pnl_pct <= 0 or total_pnl_pct >= 0)\n"
        "signal = 'BUY' if ok else 'HOLD'\n"
    )
    assert validate_code(code)[0] is True
    cs = CompiledStrategy(code)
    out = cs.decide(250, _candles(), day_pnl_pct=-1.0, consec_losses=1,
                    dd_from_peak_pct=2.0, trades_today=3, total_pnl_pct=1.0)
    assert out[0] == "BUY"


def test_hour_minute_dow_and_vwap_exposed():
    code = ("ok = (0 <= hour <= 23) and (0 <= minute <= 59) and (0 <= dow <= 6) "
            "and not isnan(vwap(20))\nsignal = 'BUY' if ok and close > 0 else 'HOLD'\n")
    assert validate_code(code)[0] is True
    assert CompiledStrategy(code).decide(250, _candles())[0] in ("BUY", None)


def test_fx_min_stop_units():
    assert math.isclose(_min_stop_price(MARKETS["EURUSD"]), 0.0006, abs_tol=1e-9)
    assert _min_stop_price(MARKETS["US500"]) == MARKETS["US500"].min_stop_points


def test_default_and_pip_costs():
    assert default_cost_points(MARKETS["EURUSD"]) > 0
    assert math.isclose(cost_points_from_pips(MARKETS["EURUSD"], 1.0), 0.0001, abs_tol=1e-12)
    assert cost_points_from_pips(MARKETS["US500"], 1.0) == 1.0


def test_costs_reduce_pnl():
    code = "signal = 'BUY' if i % 30 == 5 else ('FLAT' if i % 30 == 20 else 'HOLD')\n"
    strat = {"name": "t", "kind": "custom", "code": code}
    free = run_backtest(_candles(400), MARKETS["US500"], mc_runs=20, strategy=strat, cost_points=0.0)
    paid = run_backtest(_candles(400), MARKETS["US500"], mc_runs=20, strategy=strat, cost_points=5.0)
    assert paid.final_equity <= free.final_equity  # costs can only hurt


def test_snippet_stop_target_override():
    cs = CompiledStrategy("signal = 'BUY'\nstop_mult = 2.0\ntarget_rr = 8.0\n")
    cs.decide(50, _candles())
    assert cs.last_stop_mult == 2.0 and cs.last_target_rr == 8.0
