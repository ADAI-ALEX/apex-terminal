"""Backtest engine smoke tests — runs on synthetic candles, validates the shape."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from apex.backtest import run_backtest
from apex.config import MARKETS
from apex.models import Candle


def _trending_candles(n: int = 300) -> list[Candle]:
    """A noisy uptrend so strategies actually fire."""
    out: list[Candle] = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    price = 5000.0
    for i in range(n):
        drift = math.sin(i / 25.0) * 6.0
        price += drift + (3.0 if i % 3 == 0 else -2.0)
        o = price
        c = price + drift
        hi = max(o, c) + 4
        lo = min(o, c) - 4
        out.append(Candle(time=base + timedelta(minutes=15 * i), open=o, high=hi, low=lo, close=c, volume=100))
    return out


def test_backtest_runs_and_returns_metrics():
    res = run_backtest(_trending_candles(), MARKETS["US500"], starting_equity=100_000, mc_runs=100)
    d = res.to_dict()
    assert d["market"] == "US500"
    assert d["bars"] == 300
    assert d["starting_equity"] == 100_000
    assert isinstance(d["trades"], int)
    assert 0.0 <= d["win_rate"] <= 100.0
    assert isinstance(d["equity_curve"], list) and len(d["equity_curve"]) > 0
    assert "monte_carlo" in d


def test_backtest_handles_thin_data():
    # Fewer than warmup bars → no trades, but must not crash.
    res = run_backtest(_trending_candles(40), MARKETS["US500"], warmup=60, mc_runs=10)
    assert res.trades == 0
    assert res.total_return_pct == 0.0
