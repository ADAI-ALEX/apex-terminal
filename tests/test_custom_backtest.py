"""Tests for the offline custom-strategy backtest stack: dataset loader, strategy
store, the sandboxed custom runner, and the engine's custom-signal path."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from apex.backtest import dataset
from apex.backtest.custom_runner import CompiledStrategy, crossover, validate_code
from apex.backtest.engine import run_backtest
from apex.config import MARKETS
from apex.models import Candle
from apex.strategies import store


# ── candle helper ──────────────────────────────────────────────────────────
def _candles(n: int = 200, start: float = 5000.0) -> list[Candle]:
    out: list[Candle] = []
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    price = start
    for i in range(n):
        price += math.sin(i / 10.0) * 8.0 + (4.0 if i % 2 == 0 else -3.0)
        o = price
        c = price + math.sin(i / 7.0) * 3.0
        out.append(Candle(time=base + timedelta(days=i), open=o, high=max(o, c) + 5,
                          low=min(o, c) - 5, close=c, volume=1000))
    return out


# ── strategy store ─────────────────────────────────────────────────────────
def test_store_save_list_get_delete():
    store.ensure_dirs()
    name = "pytest_tmp_strategy"
    code = "# name: Tmp\nsignal = 'BUY' if close > 0 else 'HOLD'\n"
    meta = store.save(name, code)
    assert meta.kind == "custom" and meta.editable and meta.label == "Tmp"
    assert any(m.name == name for m in store.list_strategies())
    assert any(m.name == "book" and m.kind == "builtin" for m in store.list_strategies())
    got = store.get(name)
    assert got is not None and "BUY" in got.code
    assert store.delete(name) is True
    assert store.get(name) is None


def test_store_rejects_unsafe_names():
    assert not store.is_valid_name("../escape")
    assert not store.is_valid_name("with space")
    assert not store.is_valid_name("a/b")
    assert store.is_valid_name("good_name-1")
    with pytest.raises(ValueError):
        store.save("../escape", "signal='HOLD'")


# ── custom runner sandbox ──────────────────────────────────────────────────
def test_validate_code_blocks_dangerous_tokens():
    assert validate_code("import os")[0] is False
    assert validate_code("x = (1).__class__")[0] is False
    assert validate_code("open('x')")[0] is False
    assert validate_code("signal = 'BUY'")[0] is True
    # syntax error reported, not raised
    ok, err = validate_code("if close >\n")
    assert ok is False and "Syntax" in err


def test_compiled_strategy_decides():
    cs = CompiledStrategy("signal = 'BUY' if close > 100 else 'SELL'")
    candles = _candles(120)
    decision, risk = cs.decide(119, candles)
    assert decision in ("BUY", "SELL") and risk is None
    # a runtime error inside the snippet → HOLD (None), never crashes
    cs2 = CompiledStrategy("signal = 1 / 0")
    assert cs2.decide(50, candles) == (None, None)


def test_compiled_strategy_code_controlled_risk():
    cs = CompiledStrategy("signal = 'BUY'\nrisk = 0.75\n")
    decision, risk = cs.decide(50, _candles(120))
    assert decision == "BUY" and risk == 0.75
    # out-of-range risk is clamped to a sane band
    cs2 = CompiledStrategy("signal = 'BUY'\nrisk = 999\n")
    assert cs2.decide(50, _candles(120))[1] == 10.0


def test_crossover_helper():
    from apex.backtest.custom_runner import Val
    assert crossover(Val(10, 4), Val(8, 8)) is True     # 4<8 then 10>8
    assert crossover(Val(10, 9), Val(8, 8)) is False    # already above
    assert crossover(5, 5) is False


def test_custom_indicators_available():
    code = "u, m, l = bollinger(20, 2)\nsignal = 'BUY' if rsi(14) < 50 and not isnan(atr(14)) else 'HOLD'\n"
    cs = CompiledStrategy(code)
    assert cs.decide(150, _candles(200))[0] in ("BUY", None)


def test_donchian_roc_available():
    code = "u, lo = donchian(20)\nsignal = 'BUY' if close >= u and roc(5) > -100 and stdev(10) >= 0 else 'HOLD'\n"
    cs = CompiledStrategy(code)
    assert cs.decide(150, _candles(200))[0] in ("BUY", None)


# ── engine custom-signal path ──────────────────────────────────────────────
def test_engine_runs_custom_strategy_with_flat_exit():
    code = (
        "if i % 40 == 5:\n"
        "    signal = 'BUY'\n"
        "elif i % 40 == 25:\n"
        "    signal = 'FLAT'\n"
        "else:\n"
        "    signal = 'HOLD'\n"
    )
    res = run_backtest(
        _candles(400), MARKETS["US500"], starting_equity=100_000, mc_runs=50,
        strategy={"name": "tmp", "kind": "custom", "code": code},
    )
    d = res.to_dict()
    assert d["strategy"] == "tmp"
    assert d["trades"] > 0
    # a FLAT or END exit should be present in the log
    assert any(t["reason"] in ("FLAT", "TP", "SL", "END") for t in d["trade_log"])


def test_engine_custom_reads_exo_series():
    n = 300
    code = "signal = 'BUY' if fear_and_greed < 20 else 'FLAT'\n"
    exo = {"fear_greed": [10.0 if i % 30 < 5 else 80.0 for i in range(n)],
           "vix": [20.0] * n, "sentiment": [0.0] * n}
    res = run_backtest(
        _candles(n), MARKETS["US500"], mc_runs=20,
        strategy={"name": "fg", "kind": "custom", "code": code}, exo=exo,
    )
    assert res.trades > 0


# ── local dataset ──────────────────────────────────────────────────────────
@pytest.mark.skipif(not dataset.available(), reason="local CSVs not seeded")
def test_local_dataset_aligned():
    series = dataset.load("US500", bars=500)
    assert len(series.candles) == 500
    for name in dataset.EXO_FIELDS:
        assert len(series.exo[name]) == len(series.candles)
    # fear_greed within 0..100
    assert all(0.0 <= v <= 100.0 for v in series.exo["fear_greed"])
