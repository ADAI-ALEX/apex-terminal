"""Strategy + regime detector unit tests."""

from __future__ import annotations

from apex.config import MARKETS, Direction, Regime
from apex.models import IndicatorSnapshot
from apex.strategies import AtrBreakoutStrategy, EmaTrendStrategy, RsiReversionStrategy
from apex.strategies.regime import classify
from tests.conftest import make_candles

FTSE = MARKETS["FTSE100"]


def _snap(**overrides) -> IndicatorSnapshot:
    base = dict(
        epic=FTSE.epic, market_key=FTSE.key, price=8200.0,
        ema_fast=8210.0, ema_mid=8200.0, ema_slow=8180.0,
        rsi=58.0, macd=3.0, macd_signal=1.0, macd_hist=2.0,
        atr=15.0, atr_prev=14.0, bb_upper=8260.0, bb_mid=8200.0, bb_lower=8140.0,
        adx=30.0, regime=Regime.TRENDING,
    )
    base.update(overrides)
    return IndicatorSnapshot(**base)


# ── EMA trend ──────────────────────────────────────────────────────────────
def test_ema_trend_fires_buy_on_bull_stack():
    sig = EmaTrendStrategy().evaluate(FTSE, _snap(), make_candles([8200] * 60))
    assert sig is not None
    assert sig.direction is Direction.BUY
    assert sig.stop < sig.entry < sig.target
    assert sig.target_rr == EmaTrendStrategy().p.ema_target_rr


def test_ema_trend_fires_sell_on_bear_stack():
    snap = _snap(ema_fast=8180.0, ema_mid=8200.0, ema_slow=8210.0, macd_hist=-2.0)
    sig = EmaTrendStrategy().evaluate(FTSE, snap, make_candles([8200] * 60))
    assert sig is not None and sig.direction is Direction.SELL
    assert sig.stop > sig.entry > sig.target


def test_ema_trend_no_signal_when_rsi_out_of_band():
    assert EmaTrendStrategy().evaluate(FTSE, _snap(rsi=85.0), make_candles([8200] * 60)) is None


def test_ema_trend_no_signal_without_atr():
    assert EmaTrendStrategy().evaluate(FTSE, _snap(atr=None), make_candles([8200] * 60)) is None


# ── Authority gating ─────────────────────────────────────────────────────────
def test_authority_gating():
    s = EmaTrendStrategy()
    assert s.has_authority(Regime.TRENDING) is True
    assert s.has_authority(Regime.RANGING) is False
    assert s.has_authority(None) is True
    assert AtrBreakoutStrategy().has_authority(Regime.RANGING) is True  # all regimes


# ── Regime detector ──────────────────────────────────────────────────────────
def test_regime_trending_on_high_adx():
    assert classify(FTSE, _snap(adx=30.0, atr=15.0, atr_prev=14.8)) is Regime.TRENDING


def test_regime_ranging_on_low_adx():
    assert classify(FTSE, _snap(adx=15.0, atr=15.0, atr_prev=14.9)) is Regime.RANGING


def test_regime_volatile_on_atr_spike():
    # ATR roc = (20-10)/10 = 1.0 >> 0.25 → VOLATILE regardless of ADX.
    assert classify(FTSE, _snap(adx=30.0, atr=20.0, atr_prev=10.0)) is Regime.VOLATILE


# ── Smoke: no crash on insufficient data ─────────────────────────────────────
def test_strategies_handle_short_history():
    short = make_candles([8200, 8201, 8202])
    snap = _snap()
    assert RsiReversionStrategy().evaluate(FTSE, snap, short) is None
    assert AtrBreakoutStrategy().evaluate(FTSE, snap, short) is None
