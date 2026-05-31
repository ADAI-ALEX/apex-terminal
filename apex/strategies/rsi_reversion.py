"""RSI Mean Reversion — fades extremes in a range.

Long when RSI crosses back above the oversold line from below while price is near
the lower Bollinger band and ATR shows the market is still active. Short is the
mirror near the upper band. Authority: RANGING.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.config import Direction, Market, Regime
from apex.indicators.engine import rsi as rsi_value
from apex.models import Candle, IndicatorSnapshot, Signal
from apex.strategies.base import Strategy


class RsiReversionStrategy(Strategy):
    name = "rsi_reversion"
    authority = (Regime.RANGING,)

    def evaluate(
        self, market: Market, snapshot: IndicatorSnapshot, candles: Sequence[Candle]
    ) -> Signal | None:
        s = snapshot
        if None in (s.rsi, s.bb_lower, s.bb_upper, s.atr) or len(candles) < self.p.rsi_period + 2:
            return None

        # RSI on the prior bar, to detect a cross (need previous close excluded).
        prev_closes = [c.close for c in candles[:-1]]
        prev_rsi = rsi_value(prev_closes, self.p.rsi_period)
        if prev_rsi is None:
            return None

        near_lower = s.price <= s.bb_lower * 1.001  # type: ignore[operator]
        near_upper = s.price >= s.bb_upper * 0.999  # type: ignore[operator]
        active = s.atr is not None and s.atr > 0

        crossed_up = prev_rsi < self.p.rsi_oversold <= s.rsi  # type: ignore[operator]
        crossed_down = prev_rsi > self.p.rsi_overbought >= s.rsi  # type: ignore[operator]

        if crossed_up and near_lower and active:
            return self._build_signal(
                market, s, Direction.BUY, self.p.reversion_target_rr,
                confidence=round(min(0.62 + (self.p.rsi_oversold - prev_rsi) * 0.01, 0.85), 2),
                rationale=f"RSI cross up {prev_rsi:.0f}->{s.rsi:.0f} at lower BB {s.bb_lower:.1f}",
            )
        if crossed_down and near_upper and active:
            return self._build_signal(
                market, s, Direction.SELL, self.p.reversion_target_rr,
                confidence=round(min(0.62 + (prev_rsi - self.p.rsi_overbought) * 0.01, 0.85), 2),
                rationale=f"RSI cross down {prev_rsi:.0f}->{s.rsi:.0f} at upper BB {s.bb_upper:.1f}",
            )
        return None
