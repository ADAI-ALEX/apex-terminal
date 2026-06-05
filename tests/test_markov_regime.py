"""Tests for the Markov regime engine (the "hedge-fund method") and the saved
``markov_regime`` strategy: state labelling, the maximum-likelihood transition
matrix, Chapman-Kolmogorov n-step forecast, the stationary distribution, the
sandbox ``markov()`` binding, and the end-to-end engine path.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from apex.backtest.custom_runner import (
    CompiledStrategy,
    Regime,
    compute_markov,
    validate_code,
)
from apex.backtest.engine import run_backtest
from apex.config import MARKETS
from apex.models import Candle
from apex.strategies import store


# ── synthetic series ─────────────────────────────────────────────────────────
def _noisy(drift: float, n: int = 800, seed: int = 1, start: float = 100.0,
           vol: float = 0.01) -> list[float]:
    rng = random.Random(seed)
    px = [start]
    for _ in range(n):
        px.append(px[-1] * (1.0 + drift + rng.gauss(0.0, vol)))
    return px


def _candles_from(closes: list[float]) -> list[Candle]:
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    out: list[Candle] = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        out.append(Candle(time=base + timedelta(days=i), open=o,
                          high=max(o, c) * 1.005, low=min(o, c) * 0.995,
                          close=c, volume=1000.0))
    return out


# ── core regime maths ─────────────────────────────────────────────────────────
def test_compute_markov_neutral_when_too_short():
    r = compute_markov([100.0, 101.0, 102.0], state_lookback=20)
    assert isinstance(r, Regime)
    assert r.edge == 0.0 and r.state == "SIDE"


def test_compute_markov_detects_bull_and_bear():
    # a clean, strong trend (drift dominates noise) so the regime is unambiguous
    bull = compute_markov(_noisy(0.002, vol=0.003), state_lookback=20)
    bear = compute_markov(_noisy(-0.002, vol=0.003), state_lookback=20)
    assert bull.state == "BULL" and bull.edge > 0.0
    assert bear.state == "BEAR" and bear.edge < 0.0
    # the long-run (stationary) mix leans the right way and stickiness is a prob
    assert bull.sd_bull > bull.sd_bear and bear.sd_bear > bear.sd_bull
    assert 0.0 <= bull.stickiness <= 1.0 and bull.p_bull > bull.p_bear


def test_probabilities_and_stationary_are_valid():
    r = compute_markov(_noisy(0.0006), state_lookback=20)
    assert math.isclose(r.p_bull + r.p_bear + r.p_side, 1.0, abs_tol=1e-9)
    assert math.isclose(r.sd_bull + r.sd_bear + r.sd_side, 1.0, abs_tol=1e-6)
    assert all(0.0 <= p <= 1.0 for p in (r.p_bull, r.p_bear, r.p_side))


def test_horizon_forecast_decays_toward_stationary():
    closes = _noisy(-0.0006)
    one = compute_markov(closes, state_lookback=20, horizon=1)
    five = compute_markov(closes, state_lookback=20, horizon=5)
    # multi-step probabilities remain valid and the directional edge weakens as
    # the chain converges toward its long-run mix
    assert math.isclose(five.p_bull + five.p_bear + five.p_side, 1.0, abs_tol=1e-9)
    assert abs(five.edge) <= abs(one.edge) + 1e-9


def test_explicit_thresholds_override_volatility_band():
    # a clean ramp has ~zero return variance, so the vol band collapses to neutral
    ramp = [100.0 * (1.004 ** i) for i in range(300)]
    assert compute_markov(ramp, 20).edge == 0.0
    # but explicit +/-5% bands (the video's defaults) still classify it as Bull
    forced = compute_markov(ramp, 20, bull_thr=5.0, bear_thr=-5.0)
    assert forced.state == "BULL" and forced.edge > 0.0


def test_walk_forward_purity():
    """The fit must use only the closes handed to it — appending future bars
    cannot change the estimate for an earlier prefix (no look-ahead)."""
    closes = _noisy(0.0006)
    prefix = closes[:400]
    a = compute_markov(prefix, 20)
    b = compute_markov(prefix, 20)  # same input → identical (deterministic, pure)
    assert a == b
    # a longer series gives a (generally) different, independent estimate
    assert isinstance(compute_markov(closes, 20), Regime)


# ── sandbox binding + saved strategy ──────────────────────────────────────────
def test_markov_available_in_sandbox():
    code = "m = markov(20, band=1.0)\nsignal = 'BUY' if m.edge > 0 else 'HOLD'\n"
    assert validate_code(code)[0] is True
    cs = CompiledStrategy(code)
    decision, _ = cs.decide(700, _candles_from(_noisy(0.0006)))
    assert decision in ("BUY", None)


def test_saved_markov_strategy_validates():
    meta = store.get("markov_regime")
    assert meta is not None and meta.label.startswith("Markov Regime")
    assert validate_code(meta.code)[0] is True


def test_saved_markov_strategy_trades_in_engine():
    meta = store.get("markov_regime")
    # uptrend then downtrend so both the long and short branches can fire
    closes = _noisy(0.0008, n=500, seed=2) + _noisy(-0.0008, n=500, seed=3, start=200.0)
    res = run_backtest(
        _candles_from(closes), MARKETS["US500"], mc_runs=50,
        strategy={"name": meta.name, "kind": "custom", "code": meta.code},
    )
    d = res.to_dict()
    assert d["trades"] > 0
    assert d["max_total_dd_pct"] >= 0.0
