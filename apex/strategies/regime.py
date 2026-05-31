"""Regime detector — classifies the market every Tier-2 cycle.

Uses ADX for trend strength and the ATR rate-of-change for volatility:

* ATR ROC above ``atr_roc_volatile_pct``  → VOLATILE (overrides everything)
* ADX above ``adx_trend_threshold``        → TRENDING
* ADX below ``adx_range_threshold``        → RANGING
* otherwise                                 → carry the instrument's preferred regime

Claude agents may override the classification on macro context.
"""

from __future__ import annotations

from apex.config import Market, Regime, StrategyParams, get_settings
from apex.models import IndicatorSnapshot


def classify(
    market: Market, snapshot: IndicatorSnapshot, params: StrategyParams | None = None
) -> Regime:
    p = params or get_settings().strategy

    # Volatility spike takes priority.
    if snapshot.atr is not None and snapshot.atr_prev not in (None, 0):
        roc = abs(snapshot.atr - snapshot.atr_prev) / snapshot.atr_prev  # type: ignore[operator]
        if roc >= p.atr_roc_volatile_pct:
            return Regime.VOLATILE

    if snapshot.adx is not None:
        if snapshot.adx >= p.adx_trend_threshold:
            return Regime.TRENDING
        if snapshot.adx <= p.adx_range_threshold:
            return Regime.RANGING

    return market.preferred_regime
