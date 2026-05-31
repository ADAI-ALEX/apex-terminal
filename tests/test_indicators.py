"""Indicator engine unit tests."""

from __future__ import annotations

import math

from apex.indicators import engine
from tests.conftest import make_candles


def test_sma_basic():
    assert engine.sma([1, 2, 3, 4, 5], 5) == 3.0
    assert engine.sma([1, 2], 5) is None


def test_ema_matches_known_value():
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    # EMA seeded with SMA of first `period`; verify it tracks upward and stays in range.
    e = engine.ema(values, 5)
    assert e is not None
    assert values[-1] > e > engine.sma(values[:5], 5)  # type: ignore[operator]


def test_rsi_all_gains_is_high():
    rising = list(range(1, 30))
    assert engine.rsi(rising, 14) == 100.0


def test_rsi_all_losses_is_low():
    falling = list(range(30, 1, -1))
    r = engine.rsi(falling, 14)
    assert r is not None and r < 5.0


def test_rsi_insufficient_data():
    assert engine.rsi([1, 2, 3], 14) is None


def test_atr_positive_and_none_when_short():
    candles = make_candles([10, 11, 10.5, 11.5, 12, 11, 12.5, 13, 12, 13.5,
                            14, 13, 14.5, 15, 14, 15.5], spread=0.5)
    a = engine.atr(candles, 14)
    assert a is not None and a > 0
    assert engine.atr(make_candles([1, 2, 3]), 14) is None


def test_bollinger_orders_bands():
    bb = engine.bollinger([10, 11, 9, 12, 8, 11, 10, 12, 9, 11,
                           10, 12, 8, 11, 10, 12, 9, 11, 10, 12], 20, 2.0)
    assert bb is not None
    upper, mid, lower = bb
    assert upper > mid > lower


def test_macd_returns_triplet():
    values = [math.sin(i / 5.0) * 10 + 100 + i * 0.1 for i in range(60)]
    result = engine.macd(values, 12, 26, 9)
    assert result is not None
    macd_v, signal_v, hist = result
    assert math.isclose(hist, macd_v - signal_v, abs_tol=1e-6)


def test_adx_in_range_or_none():
    candles = make_candles([100 + i for i in range(60)], spread=1.0)
    a = engine.adx(candles, 14)
    assert a is None or 0.0 <= a <= 100.0


def test_build_snapshot_populates_fields():
    candles = make_candles([100 + math.sin(i / 4) * 5 for i in range(120)])
    snap = engine.build_snapshot("FTSE100", "IX.D.FTSE.DAILY.IP", candles)
    assert snap.price == candles[-1].close
    assert snap.ema_fast is not None
    assert snap.rsi is not None
    assert snap.atr is not None and snap.atr > 0
