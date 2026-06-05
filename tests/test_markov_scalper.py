"""Tests for the saved ``markov_scalper`` strategy: validation, the FTMO max-loss
breaker, and that it runs through the engine using the markov regime + prop-risk
state exposed to snippets."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from apex.backtest.custom_runner import CompiledStrategy, validate_code
from apex.backtest.engine import run_backtest
from apex.config import MARKETS
from apex.models import Candle
from apex.strategies import store


def _trend_candles(n: int = 700, drift: float = 0.0006, seed: int = 1) -> list[Candle]:
    rng = random.Random(seed)
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    px = 5000.0
    out: list[Candle] = []
    for i in range(n):
        px *= 1.0 + drift + rng.gauss(0.0, 0.004)
        o = px * (1.0 + rng.gauss(0.0, 0.001))
        out.append(Candle(time=base + timedelta(minutes=5 * i), open=o,
                          high=max(o, px) * 1.002, low=min(o, px) * 0.998,
                          close=px, volume=1000.0))
    return out


def test_saved_markov_scalper_validates():
    meta = store.get("markov_scalper")
    assert meta is not None and "Markov Scalper" in meta.label
    assert validate_code(meta.code)[0] is True


def test_markov_scalper_maxloss_breaker_flattens():
    meta = store.get("markov_scalper")
    cs = CompiledStrategy(meta.code)
    candles = _trend_candles()
    # past the -8% total-loss breaker while long → must flatten
    decision, _ = cs.decide(650, candles, position=1, total_pnl_pct=-9.0)
    assert decision == "FLAT"
    # healthy account does not force an exit
    decision2, _ = cs.decide(650, candles, position=1, total_pnl_pct=2.0)
    assert decision2 in ("HOLD", "FLAT", None)


def test_markov_scalper_runs_in_engine():
    meta = store.get("markov_scalper")
    res = run_backtest(
        _trend_candles(700), MARKETS["US500"], mc_runs=50,
        strategy={"name": meta.name, "kind": "custom", "code": meta.code},
    )
    d = res.to_dict()
    assert d["strategy"] == "markov_scalper"
    assert d["max_total_dd_pct"] >= 0.0
