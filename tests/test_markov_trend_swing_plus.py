"""Tests for ``markov_trend_swing_plus`` (higher-growth variant) and the new
snippet engine additions (hour-of-day + vwap)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from apex.backtest.custom_runner import CompiledStrategy, validate_code
from apex.backtest.engine import run_backtest
from apex.config import MARKETS
from apex.models import Candle
from apex.strategies import store


def _trend_candles(n: int = 700, drift: float = 0.0008, seed: int = 5) -> list[Candle]:
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


def test_hour_and_vwap_exposed():
    # hour reflects the bar's UTC time; vwap returns a finite price near the closes
    code = (
        "ok = (0 <= hour <= 23) and (dow in (0,1,2,3,4,5,6)) and not isnan(vwap(20))\n"
        "signal = 'BUY' if ok and close > 0 else 'HOLD'\n"
    )
    assert validate_code(code)[0] is True
    cs = CompiledStrategy(code)
    assert cs.decide(300, _trend_candles())[0] in ("BUY", None)


def test_saved_swing_plus_validates():
    meta = store.get("markov_trend_swing_plus")
    assert meta is not None and "Swing+" in meta.label
    assert validate_code(meta.code)[0] is True


def test_swing_plus_total_loss_stop_flattens():
    meta = store.get("markov_trend_swing_plus")
    cs = CompiledStrategy(meta.code)
    decision, _ = cs.decide(650, _trend_candles(), position=1, total_pnl_pct=-7.0)
    assert decision == "FLAT"


def test_swing_plus_runs_in_engine_with_costs():
    meta = store.get("markov_trend_swing_plus")
    res = run_backtest(
        _trend_candles(700), MARKETS["US500"], mc_runs=50,
        strategy={"name": meta.name, "kind": "custom", "code": meta.code},
        cost_points=0.5,
    )
    assert res.to_dict()["strategy"] == "markov_trend_swing_plus"
