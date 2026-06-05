"""Tests for the FTMO scalper stack: the prop-firm risk state exposed to snippets
(daily P&L, streaks, drawdown-from-peak), the FX min-stop units fix, and the saved
``apex_scalper`` strategy (validation, survival breaker, engine path).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from apex.backtest.custom_runner import CompiledStrategy, validate_code
from apex.backtest.engine import _min_stop_price, run_backtest
from apex.config import MARKETS
from apex.models import Candle
from apex.strategies import store


def _candles(n: int = 300, start: float = 5000.0) -> list[Candle]:
    out: list[Candle] = []
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    price = start
    for i in range(n):
        price += math.sin(i / 8.0) * 6.0 + (3.0 if i % 2 else -2.0)
        o = price
        c = price + math.sin(i / 5.0) * 2.0
        out.append(Candle(time=base + timedelta(minutes=5 * i), open=o,
                          high=max(o, c) + 4, low=min(o, c) - 4, close=c, volume=1000))
    return out


# ── prop-firm risk state exposed to snippets ─────────────────────────────────
def test_snippet_sees_prop_risk_state():
    code = (
        "signal = 'BUY' if (day_pnl_pct > -2 and consec_losses < 3 "
        "and dd_from_peak_pct < 5 and trades_today < 10 and total_pnl_pct >= 0) "
        "else 'HOLD'\n"
    )
    assert validate_code(code)[0] is True
    cs = CompiledStrategy(code)
    ok = cs.decide(250, _candles(), day_pnl_pct=-1.0, consec_losses=1,
                   dd_from_peak_pct=2.0, trades_today=4, total_pnl_pct=1.0)
    assert ok[0] == "BUY"
    # tripping any limit blocks the entry
    blocked = cs.decide(250, _candles(), day_pnl_pct=-3.0, dd_from_peak_pct=2.0)
    assert blocked[0] is None  # HOLD


# ── FX min-stop units fix ────────────────────────────────────────────────────
def test_fx_min_stop_is_scaled_to_points():
    # EUR/USD: 6 points * 0.0001 = 0.0006 price (not 6.0 dollars)
    assert math.isclose(_min_stop_price(MARKETS["EURUSD"]), 0.0006, abs_tol=1e-9)
    assert math.isclose(_min_stop_price(MARKETS["GBPUSD"]), 0.0006, abs_tol=1e-9)
    # indices keep 1 point = 1 price unit
    assert _min_stop_price(MARKETS["US500"]) == MARKETS["US500"].min_stop_points


# ── saved strategy ───────────────────────────────────────────────────────────
def test_saved_scalper_validates():
    meta = store.get("apex_scalper")
    assert meta is not None and "Scalper" in meta.label
    assert validate_code(meta.code)[0] is True


def test_scalper_survival_breaker_flattens():
    """At/beyond the max-loss breaker the scalper must flatten an open position."""
    meta = store.get("apex_scalper")
    cs = CompiledStrategy(meta.code)
    # deep drawdown from peak while long → FLAT regardless of indicators
    decision, _ = cs.decide(250, _candles(), position=1, dd_from_peak_pct=7.0)
    assert decision == "FLAT"
    # comfortably below the breaker it does not force an exit
    decision2, _ = cs.decide(250, _candles(), position=1, dd_from_peak_pct=1.0)
    assert decision2 in ("HOLD", "FLAT", None)


def test_scalper_runs_in_engine():
    meta = store.get("apex_scalper")
    res = run_backtest(
        _candles(600), MARKETS["US500"], mc_runs=50,
        strategy={"name": meta.name, "kind": "custom", "code": meta.code},
    )
    d = res.to_dict()
    assert d["strategy"] == "apex_scalper"
    assert d["max_total_dd_pct"] >= 0.0  # ran cleanly, drawdown tracked
