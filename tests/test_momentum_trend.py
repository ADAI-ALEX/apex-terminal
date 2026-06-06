"""Tests for the saved ``momentum_trend`` strategy (Turtle/CTA trend-follower):
validation, the snippet's stop/target overrides, and engine run with costs."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from apex.backtest.custom_runner import CompiledStrategy, validate_code
from apex.backtest.engine import run_backtest
from apex.config import MARKETS
from apex.models import Candle
from apex.strategies import store


def _trend_candles(n: int = 200, start: float = 2000.0) -> list[Candle]:
    """A clean rising trend so the breakout entry + trailing exit both fire."""
    out: list[Candle] = []
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    price = start
    for i in range(n):
        price *= 1.0 + 0.004 + math.sin(i / 11.0) * 0.006
        o = price * 0.999
        out.append(Candle(time=base + timedelta(days=i), open=o,
                          high=price * 1.004, low=price * 0.996, close=price, volume=1000))
    return out


def test_saved_momentum_trend_validates():
    meta = store.get("momentum_trend")
    assert meta is not None and "Momentum Trend" in meta.label
    assert validate_code(meta.code)[0] is True


def test_momentum_trend_sets_wide_stop_and_far_target():
    meta = store.get("momentum_trend")
    cs = CompiledStrategy(meta.code)
    cs.decide(150, _trend_candles())
    assert cs.last_stop_mult == 3.0 and cs.last_target_rr == 20.0  # ride winners (rr clamped to 20)


def test_momentum_trend_runs_in_engine_with_costs():
    meta = store.get("momentum_trend")
    res = run_backtest(
        _trend_candles(200), MARKETS["US500"], mc_runs=50,
        strategy={"name": meta.name, "kind": "custom", "code": meta.code},
        cost_points=0.5,
    )
    d = res.to_dict()
    assert d["strategy"] == "momentum_trend"
    assert d["trades"] >= 1  # the breakout fires in a clean trend
