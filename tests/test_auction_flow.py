"""Tests for the Auction-Market-Theory toolkit (volume_profile + cvd) and the
Auction Flow strategy.

Covers the two new primitives exposed to every custom strategy and the invariants
the FTMO strategy must hold: it is long-only (the indices drift up — shorts have no
edge), it compiles/runs without crashing, and its survival breaker flattens when the
account nears the max-loss line.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from apex.backtest.custom_runner import CompiledStrategy, _Indicators
from apex.models import Candle
from apex.strategies import store


def _bar(t: datetime, o: float, h: float, lo: float, c: float, v: float) -> Candle:
    return Candle(time=t, open=o, high=h, low=lo, close=c, volume=v)


def _base_time() -> datetime:
    return datetime(2024, 1, 1, tzinfo=timezone.utc)


# ── volume_profile ───────────────────────────────────────────────────────────
def test_volume_profile_poc_finds_high_volume_price():
    """The Point of Control sits at the price where the most volume traded."""
    t0 = _base_time()
    candles: list[Candle] = []
    for i in range(150):
        # Most bars hug 100 on heavy volume; a few drift to 110 on light volume.
        if i % 10 == 0:
            o = c = 110.0
            vol = 50.0
        else:
            o = c = 100.0
            vol = 5000.0
        candles.append(_bar(t0 + timedelta(hours=i), o, c + 0.5, c - 0.5, c, vol))
    vp = _Indicators(candles).volume_profile(120, 20)
    assert abs(float(vp.poc) - 100.0) < 1.5          # POC at the heavy-volume price
    assert float(vp.val) <= float(vp.poc) <= float(vp.vah)
    assert float(vp.width) >= 0.0


def test_volume_profile_value_area_brackets_poc():
    """Value area is a band around the POC; VAL ≤ VAH and both are finite."""
    t0 = _base_time()
    candles = [
        _bar(t0 + timedelta(hours=i), 100 + math.sin(i / 8) * 5,
             100 + math.sin(i / 8) * 5 + 2, 100 + math.sin(i / 8) * 5 - 2,
             100 + math.sin(i / 8) * 5, 1000.0)
        for i in range(140)
    ]
    vp = _Indicators(candles).volume_profile(120, 24)
    assert not math.isnan(float(vp.poc))
    assert float(vp.val) <= float(vp.vah)


def test_volume_profile_handles_missing_volume():
    """With zero volume it degrades to an equal-weight (TPO) profile, not NaN."""
    t0 = _base_time()
    candles = [_bar(t0 + timedelta(hours=i), 100 + i * 0.1, 100 + i * 0.1 + 1,
                    100 + i * 0.1 - 1, 100 + i * 0.1, 0.0) for i in range(80)]
    vp = _Indicators(candles).volume_profile(60, 16)
    assert not math.isnan(float(vp.poc))


# ── cvd ──────────────────────────────────────────────────────────────────────
def test_cvd_positive_when_closes_lead_highs():
    """Bars closing near their highs (aggressive buyers) push CVD positive."""
    t0 = _base_time()
    up = [_bar(t0 + timedelta(hours=i), 100, 101, 99.9, 100.95, 1000.0) for i in range(40)]
    dn = [_bar(t0 + timedelta(hours=i), 100, 100.1, 99, 99.05, 1000.0) for i in range(40)]
    assert float(_Indicators(up).cvd(20)) > 0
    assert float(_Indicators(dn).cvd(20)) < 0


def test_cvd_carries_previous_value():
    """CVD is a Val carrying the prior bar's value (so crossover/slope work)."""
    t0 = _base_time()
    candles = [_bar(t0 + timedelta(hours=i), 100, 101, 99, 100.5 + i * 0.01, 1000.0)
               for i in range(30)]
    cv = _Indicators(candles).cvd(20)
    assert hasattr(cv, "prev")
    assert isinstance(float(cv.prev), float)


# ── strategy invariants ──────────────────────────────────────────────────────
def _auction_flow_code() -> str:
    meta = store.get("auction_flow")
    assert meta is not None, "auction_flow strategy file must exist"
    return meta.code


def _make_series(n: int = 400) -> list[Candle]:
    t0 = _base_time()
    out: list[Candle] = []
    price = 18000.0
    for i in range(n):
        price += math.sin(i / 9.0) * 40.0 + (12.0 if i % 3 else -18.0)
        o = price
        c = price + math.sin(i / 5.0) * 15.0
        out.append(_bar(t0 + timedelta(hours=i), o, max(o, c) + 20,
                        min(o, c) - 20, c, 1000.0 + (i % 7) * 300.0))
    return out


def test_auction_flow_is_long_only():
    """The book never shorts — every decision is BUY, FLAT or hold (None)."""
    strat = CompiledStrategy(_auction_flow_code())
    candles = _make_series(400)
    decisions = set()
    for i in range(60, len(candles)):
        decision, _ = strat.decide(i, candles, position=0)
        decisions.add(decision)
    assert "SELL" not in decisions


def test_auction_flow_survival_breaker_flattens():
    """At/over the 6% drawdown line an open long is flattened."""
    strat = CompiledStrategy(_auction_flow_code())
    candles = _make_series(300)
    decision, _ = strat.decide(250, candles, position=1, dd_from_peak_pct=7.0)
    assert decision == "FLAT"


def test_auction_flow_compiles_and_runs_without_crashing():
    """A full per-bar pass produces only valid decisions and never raises."""
    strat = CompiledStrategy(_auction_flow_code())
    candles = _make_series(360)
    for i in range(60, len(candles)):
        decision, risk = strat.decide(i, candles, position=0, equity=100_000.0)
        assert decision in (None, "BUY", "SELL", "FLAT")
        assert risk is None or 0.0 < risk <= 10.0
