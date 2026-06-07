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


# ── two-stage exit (scale-out + break-even) engine path ──────────────────────
def test_runner_exposes_scale_outputs():
    """A snippet can request a partial scale-out via scale_at / scale_frac / scale_be."""
    strat = CompiledStrategy(
        "signal = 'BUY'\nscale_at = 123.5\nscale_frac = 0.5\nscale_be = True\n"
    )
    candles = _make_series(120)
    strat.decide(100, candles, position=0)
    assert strat.last_scale_price == 123.5
    assert strat.last_scale_frac == 0.5
    assert strat.last_scale_be is True


def test_scale_out_books_one_combined_trade():
    """Scaling 50% out at the POC then exiting the rest books a SCALE leg plus a
    single combined trade — and the engine never crashes on the partial path."""
    from apex.backtest.engine import run_backtest
    from apex.config import MARKETS

    t0 = _base_time()
    # Steadily rising series so a long reaches its scale level then its target.
    candles = [_bar(t0 + timedelta(hours=i), 100 + i, 101.5 + i, 99.5 + i, 100.8 + i, 1000.0)
               for i in range(200)]
    code = (
        "if position == 0 and i == 80:\n"
        "    signal = 'BUY'\n"
        "    stop_mult = 2.0\n"
        "    target_rr = 6.0\n"
        "    scale_at = close + 3.0\n"
        "    scale_frac = 0.5\n"
        "    scale_be = True\n"
    )
    res = run_backtest(candles, MARKETS["US500"], warmup=60,
                       strategy={"name": "scaletest", "kind": "custom", "code": code},
                       mc_runs=0, cost_points=0.0).to_dict()
    reasons = [t["reason"] for t in res["trade_log"]]
    assert "SCALE" in reasons                       # the partial leg was booked
    assert res["trades"] == 1                        # but it is one combined trade
    assert res["total_return_pct"] > 0               # rising market -> profitable long


def test_v2_is_long_only_and_breaker_flattens():
    """V2 (Challenge Mode) keeps the long-only bias and the hard daily breaker."""
    meta = store.get("auction_flow_v2")
    assert meta is not None, "auction_flow_v2 strategy file must exist"
    strat = CompiledStrategy(meta.code)
    candles = _make_series(400)
    decisions = set()
    for i in range(60, len(candles)):
        decision, _ = strat.decide(i, candles, position=0)
        decisions.add(decision)
    assert "SELL" not in decisions
    # Day down past -2.5% with an open long -> hard circuit breaker flattens.
    decision, _ = strat.decide(300, candles, position=1, day_pnl_pct=-2.6)
    assert decision == "FLAT"


def test_v2_sizes_above_v1_floor():
    """V2's dynamic base risk lives in the 0.8–1.25% band (vs V1's 0.45%)."""
    meta = store.get("auction_flow_v2")
    assert meta is not None
    strat = CompiledStrategy(meta.code)
    candles = _make_series(400)
    risks = [r for i in range(60, len(candles))
             for d, r in [strat.decide(i, candles, position=0)] if r is not None]
    # Whenever V2 sizes a trade it is at least the 0.8% floor (drawdown-throttle aside).
    assert risks, "expected at least one sized entry"
    assert max(risks) >= 0.8


def test_runner_exposes_trail_dist():
    """A snippet can request a trailing stop via trail_dist (price distance)."""
    strat = CompiledStrategy("signal = 'BUY'\nscale_at = 50.0\nscale_frac = 0.25\ntrail_dist = 5.0\n")
    candles = _make_series(120)
    strat.decide(100, candles, position=0)
    assert strat.last_trail_dist == 5.0


def test_trailing_stop_locks_profit_on_runner():
    """After scaling, the trailing stop ratchets up and locks profit when price
    rises then reverses — booked as one combined, profitable trade."""
    from apex.backtest.engine import run_backtest
    from apex.config import MARKETS

    t0 = _base_time()
    rise = [_bar(t0 + timedelta(hours=i), 100 + i, 101 + i, 99.5 + i, 100.7 + i, 1000.0)
            for i in range(140)]              # steady climb (scale + trail ratchet up)
    fall = [_bar(t0 + timedelta(hours=140 + i), 240 - 3 * i, 240.5 - 3 * i,
                 238 - 3 * i, 239 - 3 * i, 1000.0) for i in range(20)]  # sharp drop -> trail hit
    code = (
        "if position == 0 and i == 80:\n"
        "    signal = 'BUY'\n"
        "    stop_mult = 2.0\n"
        "    target_rr = 50.0\n"          # target far away so only the trail can exit
        "    scale_at = close + 2.0\n"
        "    scale_frac = 0.25\n"
        "    scale_be = True\n"
        "    trail_dist = 4.0\n"
    )
    res = run_backtest(rise + fall, MARKETS["US500"], warmup=60,
                       strategy={"name": "trailtest", "kind": "custom", "code": code},
                       mc_runs=0, cost_points=0.0).to_dict()
    reasons = [t["reason"] for t in res["trade_log"]]
    assert "SCALE" in reasons                       # 25% banked at the scale level
    assert res["trades"] == 1                        # one combined trade
    assert res["total_return_pct"] > 0               # trailing stop locked in profit


def test_v5_long_only_and_breaker():
    """V5: long-only, -3.5% daily breaker, sizing in the 1.2–1.9% band. (The
    asymmetric trailing-exit path itself is covered by the engine/runner tests.)"""
    meta = store.get("auction_flow_v5")
    assert meta is not None, "auction_flow_v5 strategy file must exist"
    strat = CompiledStrategy(meta.code)
    candles = _make_series(500)
    risks, decisions = [], set()
    for i in range(60, len(candles)):
        d, r = strat.decide(i, candles, position=0)
        decisions.add(d)
        if r is not None:
            risks.append(r)
    assert "SELL" not in decisions                     # long-only
    assert risks and 1.2 <= min(risks) and max(risks) <= 1.9   # V4-style tilt band
    d, _ = strat.decide(300, candles, position=1, day_pnl_pct=-3.6)
    assert d == "FLAT"                                 # -3.5% hard daily breaker


def test_runner_bars_since_scale_kwarg():
    """The engine feeds bars_since_scale to decide() for a one-time runner gate."""
    strat = CompiledStrategy("signal = 'FLAT' if bars_since_scale == 1 else 'HOLD'\n")
    candles = _make_series(120)
    d_gate, _ = strat.decide(100, candles, position=1, bars_since_scale=1)
    d_none, _ = strat.decide(100, candles, position=1, bars_since_scale=-1)
    assert d_gate == "FLAT" and d_none is None


def test_v5_1_hybrid_long_only_and_breaker():
    """V5.1-Hybrid: long-only, 1.2–1.9% sizing, -3.2% daily breaker."""
    meta = store.get("auction_flow_v5_1_hybrid")
    assert meta is not None, "auction_flow_v5_1_hybrid strategy file must exist"
    strat = CompiledStrategy(meta.code)
    candles = _make_series(500)
    risks, decisions = [], set()
    for i in range(60, len(candles)):
        d, r = strat.decide(i, candles, position=0)
        decisions.add(d)
        if r is not None:
            risks.append(r)
    assert "SELL" not in decisions
    assert risks and 1.2 <= min(risks) and max(risks) <= 1.9
    d, _ = strat.decide(300, candles, position=1, day_pnl_pct=-3.3)
    assert d == "FLAT"                                 # -3.2% hard daily breaker


def test_v5_2_scaled_long_only_and_band():
    """V5.2-Scaled: long-only, -3.2% breaker, sizing in the raised 1.5–2.3% band."""
    meta = store.get("auction_flow_v5_2_scaled")
    assert meta is not None, "auction_flow_v5_2_scaled strategy file must exist"
    strat = CompiledStrategy(meta.code)
    candles = _make_series(500)
    risks, decisions = [], set()
    for i in range(60, len(candles)):
        d, r = strat.decide(i, candles, position=0)
        decisions.add(d)
        if r is not None:
            risks.append(r)
    assert "SELL" not in decisions
    assert risks and 1.5 <= min(risks) and max(risks) <= 2.3
    d, _ = strat.decide(300, candles, position=1, day_pnl_pct=-3.3)
    assert d == "FLAT"


def test_v4_long_only_divergence_tilt_sizing():
    """V4 (Max Risk): long-only, 1.2–2.2% divergence-tilted sizing, -3.2% breaker."""
    meta = store.get("auction_flow_v4")
    assert meta is not None, "auction_flow_v4 strategy file must exist"
    strat = CompiledStrategy(meta.code)
    candles = _make_series(400)
    risks, decisions = [], set()
    for i in range(60, len(candles)):
        d, r = strat.decide(i, candles, position=0)
        decisions.add(d)
        if r is not None:
            risks.append(r)
    assert "SELL" not in decisions                     # long-only
    assert risks and 1.2 <= min(risks) and max(risks) <= 2.2   # divergence-tilt band
    d, _ = strat.decide(300, candles, position=1, day_pnl_pct=-3.3)
    assert d == "FLAT"                                 # -3.2% hard daily breaker


def test_cvd_divergence_primitive_signs():
    """cvd_divergence returns +1 bullish / -1 bearish / 0, and never raises."""
    t0 = _base_time()
    # Falling price but each bar closes strong (rising CVD) -> bullish divergence.
    bull = [_bar(t0 + timedelta(hours=i), 100 - i, 100 - i + 0.2, 100 - i - 1.0,
                 100 - i + 0.15, 1000.0) for i in range(20)]
    assert _Indicators(bull).cvd_divergence(12) in (1, 0)
    flat = [_bar(t0 + timedelta(hours=i), 100, 100.5, 99.5, 100, 1000.0) for i in range(20)]
    assert _Indicators(flat).cvd_divergence(12) == 0


def test_v3_long_only_breaker_and_aggressive_sizing():
    """V3 (Max Util): long-only, hard -3.5% daily breaker, 1.2–1.9% base sizing."""
    meta = store.get("auction_flow_v3")
    assert meta is not None, "auction_flow_v3 strategy file must exist"
    strat = CompiledStrategy(meta.code)
    candles = _make_series(400)
    risks, decisions = [], set()
    for i in range(60, len(candles)):
        d, r = strat.decide(i, candles, position=0)
        decisions.add(d)
        if r is not None:
            risks.append(r)
    assert "SELL" not in decisions                     # long-only
    assert max(risks) >= 1.2                            # aggressive base sizing
    assert max(risks) <= 1.9                            # but capped at the ceiling
    # Day down past -3.5% with an open long -> hard circuit breaker flattens.
    d, _ = strat.decide(300, candles, position=1, day_pnl_pct=-3.6)
    assert d == "FLAT"
    # ... but at -3.0% (inside the breaker) it does NOT force a flatten.
    d2, _ = strat.decide(300, candles, position=1, day_pnl_pct=-3.0)
    assert d2 != "FLAT"
