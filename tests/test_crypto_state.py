"""Tests for the Phase-5 crypto state engine and its new math infrastructure.

Covers: the Gaussian-HMM fit/filter primitives (correctness + walk-forward
no-lookahead), the real taker-flow primitives, the percent cost model in the
backtest engine, the macro overlay columns in the crypto seeds, and that the
shipped ``crypto_state_v1.py`` snippet validates and runs end-to-end.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apex.backtest import dataset
from apex.backtest.custom_runner import (
    CompiledStrategy,
    fit_hmm,
    hmm_filter_step,
    hmm_read,
    validate_code,
)
from apex.backtest.engine import run_backtest
from apex.backtest.runner import LOCAL_BACKTEST_MARKETS
from apex.config import get_settings
from apex.models import Candle

STRAT_PATH = Path(__file__).resolve().parents[1] / "apex" / "strategies" / "custom" / "crypto_state_v1.py"
STRAT_V2_PATH = Path(__file__).resolve().parents[1] / "apex" / "strategies" / "custom" / "crypto_state_v2.py"


def _candles(closes: list[float], start: datetime | None = None,
             minutes: int = 15) -> list[Candle]:
    t0 = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    out = []
    for i, c in enumerate(closes):
        prev = closes[i - 1] if i else c
        hi, lo = max(prev, c) * 1.001, min(prev, c) * 0.999
        out.append(Candle(time=t0 + timedelta(minutes=minutes * i),
                          open=prev, high=hi, low=lo, close=c, volume=100.0))
    return out


# ── Gaussian HMM core ────────────────────────────────────────────────────────

def test_fit_hmm_separates_volatility_regimes() -> None:
    rng = random.Random(42)
    obs = [rng.gauss(0.0, 0.1) for _ in range(600)] + [rng.gauss(0.0, 1.0) for _ in range(600)]
    params = fit_hmm(obs, n_states=2)
    assert params is not None
    pi, A, mus, vars_ = params
    assert abs(sum(pi) - 1.0) < 1e-6
    for row in A:
        assert abs(sum(row) - 1.0) < 1e-9
    sigmas = sorted(v ** 0.5 for v in vars_)
    assert sigmas[1] / sigmas[0] > 3.0, "HMM failed to separate the two vol regimes"


def test_fit_hmm_too_short_returns_none() -> None:
    assert fit_hmm([0.1, -0.2, 0.3], n_states=3) is None


def test_hmm_filter_step_normalises() -> None:
    params = fit_hmm([random.Random(1).gauss(0, 0.5) for _ in range(400)], n_states=3)
    assert params is not None
    probs = list(params[0])
    for x in (0.1, -2.0, 5.0, 0.0):
        probs = hmm_filter_step(probs, params[1], params[2], params[3], x)
        assert abs(sum(probs) - 1.0) < 1e-9
        assert all(p >= 0 for p in probs)
    state = hmm_read(params, probs, "ret")
    assert state.state in ("BULL", "BEAR", "SIDE")
    assert abs(state.p_bull + state.p_bear + state.p_side - 1.0) < 1e-6


def test_hmm_primitive_is_walk_forward() -> None:
    """The hmm() read at bar i must not change when future bars are removed."""
    rng = random.Random(7)
    closes = [100.0]
    for _ in range(1500):
        closes.append(closes[-1] * (1.0 + rng.gauss(0.0003, 0.004)))
    full = _candles(closes)
    k = 1300
    code = "h = hmm(2, 400, 48)\nsignal = 'BUY' if h.edge > 0 else 'FLAT'\n"
    s_full = CompiledStrategy(code)
    s_trunc = CompiledStrategy(code)
    trunc = full[: k + 1]
    for i in range(1200, k + 1):
        d_full = s_full.decide(i, full)
        d_trunc = s_trunc.decide(i, trunc)
        assert d_full == d_trunc, f"lookahead detected at bar {i}"


# ── real taker-flow primitives ───────────────────────────────────────────────

def test_flow_norm_reads_real_deltas() -> None:
    closes = [100.0 + 0.01 * i for i in range(60)]
    cs = _candles(closes)
    buy_deltas = [50.0] * 60
    sell_deltas = [-50.0] * 60
    code = "fn = flow_norm(5)\nsignal = 'BUY' if (not isnan(fn)) and fn > 0.2 else 'FLAT'\n"
    buy = CompiledStrategy(code, exo={"delta": buy_deltas})
    sell = CompiledStrategy(code, exo={"delta": sell_deltas})
    assert buy.decide(50, cs)[0] == "BUY"
    assert sell.decide(50, cs)[0] == "FLAT"


def test_flow_without_delta_column_is_nan_safe() -> None:
    cs = _candles([100.0] * 40)
    code = "fn = flow_norm(5)\nsignal = 'BUY' if (not isnan(fn)) and fn > 0 else 'FLAT'\n"
    s = CompiledStrategy(code, exo={})
    assert s.decide(30, cs)[0] == "FLAT"


# ── engine percent cost model ────────────────────────────────────────────────

def test_engine_cost_pct_charges_notional() -> None:
    rng = random.Random(3)
    closes = [1000.0]
    for _ in range(400):
        closes.append(closes[-1] * (1.0 + rng.gauss(0.001, 0.002)))
    cs = _candles(closes)
    code = "signal = 'BUY' if (position == 0 and i % 50 == 0) else ('FLAT' if bars_held >= 10 else 'HOLD')\n"
    st = get_settings()
    common = dict(starting_equity=100_000.0, risk_pct=1.0, params=st.strategy,
                  mc_runs=0, strategy={"name": "t", "kind": "custom", "code": code})
    free = run_backtest(cs, LOCAL_BACKTEST_MARKETS["BTCUSD"], cost_pct=0.0, **common)
    paid = run_backtest(cs, LOCAL_BACKTEST_MARKETS["BTCUSD"], cost_pct=0.5, **common)
    assert free.trades == paid.trades > 0
    assert paid.final_equity < free.final_equity, "cost_pct did not reduce equity"


# ── crypto seed data: macro overlay columns ──────────────────────────────────

@pytest.mark.skipif(not dataset.has_local("BTCUSD", "15m"), reason="no local BTC 15m seed")
def test_btc_seed_carries_macro_and_delta() -> None:
    s = dataset.load("BTCUSD", 0, timeframe="15m")
    assert len(s.candles) > 200_000
    for col in ("delta", "macro", "macro_slow"):
        assert col in s.exo and len(s.exo[col]) == len(s.candles)
    assert any(v != 0.0 for v in s.exo["macro"][60_000:61_000])
    assert any(v != 0.0 for v in s.exo["macro_slow"][60_000:61_000])


# ── the shipped strategy file ────────────────────────────────────────────────

def test_crypto_state_v1_validates() -> None:
    code = STRAT_PATH.read_text(encoding="utf-8")
    ok, err = validate_code(code)
    assert ok, err


@pytest.mark.skipif(not dataset.has_local("BTCUSD", "15m"), reason="no local BTC 15m seed")
def test_crypto_state_v1_runs_end_to_end() -> None:
    code = STRAT_PATH.read_text(encoding="utf-8")
    s = dataset.load("BTCUSD", 0, timeframe="15m")
    # a 2024H2 slice (bull/chop) where the strategy is known to trade
    idx = [i for i, c in enumerate(s.candles)
           if "2024-10-01" <= c.time.isoformat()[:10] < "2024-12-15"]
    a, b = idx[0], idx[-1] + 1
    cs = s.candles[a:b]
    exo = {n: v[a:b] for n, v in s.exo.items()}
    st = get_settings()
    r = run_backtest(cs, LOCAL_BACKTEST_MARKETS["BTCUSD"], starting_equity=100_000.0,
                     risk_pct=1.0, params=st.strategy, mc_runs=50,
                     strategy={"name": "cs1", "kind": "custom", "code": code},
                     exo=exo, cost_pct=0.12)
    assert r.bars == len(cs)
    assert r.trades >= 1, "expected at least one trade in a bull/chop slice"
    assert r.max_daily_dd_pct < 4.0
    assert r.max_total_dd_pct < 9.0


# ── Phase 5.2: the 4H series + the shipped V2 strategy file ──────────────────

@pytest.mark.skipif(not dataset.has_local("BTCUSD", "240m"), reason="no local BTC 240m seed")
def test_btc_240m_seed_carries_macro_and_delta() -> None:
    """The resampled 4H seed keeps the exo columns aligned and populated."""
    s = dataset.load("BTCUSD", 0, timeframe=dataset.suffix_for(240))
    assert len(s.candles) > 10_000
    for col in ("delta", "macro", "macro_slow"):
        assert col in s.exo and len(s.exo[col]) == len(s.candles)
    assert any(v != 0.0 for v in s.exo["macro"][4_000:4_500])
    assert any(v != 0.0 for v in s.exo["macro_slow"][4_000:4_500])
    # 4H bars must be strictly increasing on 4-hour UTC boundaries
    for prev, cur in zip(s.candles[1000:1010], s.candles[1001:1011]):
        assert (cur.time - prev.time).total_seconds() == 4 * 3600
        assert cur.time.hour % 4 == 0


def test_crypto_state_v2_validates() -> None:
    code = STRAT_V2_PATH.read_text(encoding="utf-8")
    ok, err = validate_code(code)
    assert ok, err


def test_global_macro_v4_validates_in_both_modes() -> None:
    """The V4 file must validate as shipped AND with CHALLENGE_MODE flipped."""
    code = STRAT_V2_PATH.with_name("global_macro_v4.py").read_text(encoding="utf-8")
    ok, err = validate_code(code)
    assert ok, err
    assert "CHALLENGE_MODE = False" in code, "V4 must ship in institutional mode"
    flipped = code.replace("CHALLENGE_MODE = False", "CHALLENGE_MODE = True")
    ok, err = validate_code(flipped)
    assert ok, err


def test_crypto_v3_master_validates_and_matches_v2_stack() -> None:
    """V3-master's BTC leg must stay byte-identical to V2 below the header."""
    v3_path = STRAT_V2_PATH.with_name("crypto_v3_master.py")
    code = v3_path.read_text(encoding="utf-8")
    ok, err = validate_code(code)
    assert ok, err
    strip = lambda c: "\n".join(  # noqa: E731 - test-local helper
        line for line in c.splitlines() if not line.startswith("#")).strip()
    assert strip(code) == strip(STRAT_V2_PATH.read_text(encoding="utf-8")), (
        "crypto_v3_master.py drifted from crypto_state_v2.py — keep the BTC leg identical")


@pytest.mark.skipif(not dataset.has_local("BTCUSD", "240m"), reason="no local BTC 240m seed")
def test_crypto_state_v2_runs_end_to_end() -> None:
    """The shipped V2 file trades a known bull slice inside the prop ceilings."""
    code = STRAT_V2_PATH.read_text(encoding="utf-8")
    s = dataset.load("BTCUSD", 0, timeframe=dataset.suffix_for(240))
    idx = [i for i, c in enumerate(s.candles)
           if "2024-01-01" <= c.time.isoformat()[:10] < "2024-07-01"]
    a, b = idx[0], idx[-1] + 1
    cs = s.candles[a:b]
    exo = {n: v[a:b] for n, v in s.exo.items()}
    st = get_settings()
    r = run_backtest(cs, LOCAL_BACKTEST_MARKETS["BTCUSD"], starting_equity=100_000.0,
                     risk_pct=1.0, params=st.strategy, mc_runs=50,
                     strategy={"name": "cs2", "kind": "custom", "code": code},
                     exo=exo, cost_pct=0.12)
    assert r.bars == len(cs)
    assert r.trades >= 1, "expected at least one trade in the 2024H1 bull slice"
    assert r.max_daily_dd_pct < 4.0
    assert r.max_total_dd_pct < 9.0
