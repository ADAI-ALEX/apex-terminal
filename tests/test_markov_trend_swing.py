"""Tests for the saved ``markov_trend_swing`` strategy: validation, the -6%
total-loss stop, and that it runs through the engine (incl. with costs)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from apex.backtest.custom_runner import CompiledStrategy, validate_code
from apex.backtest.engine import run_backtest
from apex.config import MARKETS
from apex.models import Candle
from apex.strategies import store


def _trend_candles(n: int = 700, drift: float = 0.0008, seed: int = 3) -> list[Candle]:
    rng = random.Random(seed)
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    px = 5000.0
    out: list[Candle] = []
    for i in range(n):
        px *= 1.0 + drift + rng.gauss(0.0, 0.004)
        o = px * (1.0 + rng.gauss(0.0, 0.001))
        out.append(Candle(time=base + timedelta(hours=i), open=o,
                          high=max(o, px) * 1.002, low=min(o, px) * 0.998,
                          close=px, volume=1000.0))
    return out


def test_saved_swing_validates():
    meta = store.get("markov_trend_swing")
    assert meta is not None and "Markov Trend" in meta.label
    assert validate_code(meta.code)[0] is True


def test_swing_total_loss_stop_flattens():
    meta = store.get("markov_trend_swing")
    cs = CompiledStrategy(meta.code)
    candles = _trend_candles()
    decision, _ = cs.decide(650, candles, position=1, total_pnl_pct=-7.0)
    assert decision == "FLAT"


def test_swing_runs_in_engine_with_costs():
    meta = store.get("markov_trend_swing")
    res = run_backtest(
        _trend_candles(700), MARKETS["US500"], mc_runs=50,
        strategy={"name": meta.name, "kind": "custom", "code": meta.code},
        cost_points=0.8,   # exercise the new cost path
    )
    d = res.to_dict()
    assert d["strategy"] == "markov_trend_swing"
    assert d["max_total_dd_pct"] >= 0.0
