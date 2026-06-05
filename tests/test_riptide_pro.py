"""Tests for the saved ``riptide_pro`` strategy (clean-data-validated daily edge):
validation, drawdown self-throttle, and engine run with costs."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from apex.backtest.custom_runner import CompiledStrategy, validate_code
from apex.backtest.engine import run_backtest
from apex.config import MARKETS
from apex.models import Candle
from apex.strategies import store


def _candles(n: int = 400, start: float = 5000.0) -> list[Candle]:
    out: list[Candle] = []
    base = datetime(2015, 1, 1, tzinfo=timezone.utc)
    price = start
    for i in range(n):
        price += math.sin(i / 9.0) * 30.0 + 4.0  # gentle uptrend + oscillation
        o = price
        c = price + math.sin(i / 4.0) * 12.0
        out.append(Candle(time=base + timedelta(days=i), open=o,
                          high=max(o, c) + 15, low=min(o, c) - 15, close=c, volume=1000))
    return out


def test_saved_riptide_pro_validates():
    meta = store.get("riptide_pro")
    assert meta is not None and "Riptide Pro" in meta.label
    assert validate_code(meta.code)[0] is True


def test_riptide_pro_daily_cap_blocks_entries():
    meta = store.get("riptide_pro")
    cs = CompiledStrategy(meta.code)
    # past the -3% daily cap, never opens a new position
    decision, _ = cs.decide(380, _candles(), position=0, day_pnl_pct=-3.5)
    assert decision in (None, "FLAT")


def test_riptide_pro_runs_in_engine_with_costs():
    meta = store.get("riptide_pro")
    res = run_backtest(
        _candles(400), MARKETS["US500"], mc_runs=50,
        strategy={"name": meta.name, "kind": "custom", "code": meta.code},
        cost_points=0.5,
    )
    d = res.to_dict()
    assert d["strategy"] == "riptide_pro"
    assert d["max_total_dd_pct"] >= 0.0
