"""EMA Trend Confluence — trades with the trend.

Long when EMA9 > EMA21 > EMA55 (stacked bullish), MACD histogram rising, and RSI
in the 45–70 momentum band. Short is the mirror. Authority: TRENDING.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.config import Direction, Market, Regime
from apex.models import Candle, IndicatorSnapshot, Signal
from apex.strategies.base import Strategy


class EmaTrendStrategy(Strategy):
    name = "ema_trend"
    authority = (Regime.TRENDING,)

    def evaluate(
        self, market: Market, snapshot: IndicatorSnapshot, candles: Sequence[Candle]
    ) -> Signal | None:
        s = snapshot
        if None in (s.ema_fast, s.ema_mid, s.ema_slow, s.rsi, s.macd_hist):
            return None

        bull_stack = s.ema_fast > s.ema_mid > s.ema_slow  # type: ignore[operator]
        bear_stack = s.ema_fast < s.ema_mid < s.ema_slow  # type: ignore[operator]
        macd_rising = s.macd_hist > 0  # type: ignore[operator]
        rsi_band = self.p.ema_rsi_floor <= s.rsi <= self.p.ema_rsi_ceiling  # type: ignore[operator]

        if bull_stack and macd_rising and rsi_band:
            conf = self._confidence(s, Direction.BUY)
            return self._build_signal(
                market, s, Direction.BUY, self.p.ema_target_rr, conf,
                f"EMA stacked bull ({s.ema_fast:.1f}>{s.ema_mid:.1f}>{s.ema_slow:.1f}), "
                f"MACD hist {s.macd_hist:.2f}>0, RSI {s.rsi:.0f} in band",
            )
        if bear_stack and not macd_rising and rsi_band:
            conf = self._confidence(s, Direction.SELL)
            return self._build_signal(
                market, s, Direction.SELL, self.p.ema_target_rr, conf,
                f"EMA stacked bear ({s.ema_fast:.1f}<{s.ema_mid:.1f}<{s.ema_slow:.1f}), "
                f"MACD hist {s.macd_hist:.2f}<0, RSI {s.rsi:.0f} in band",
            )
        return None

    def _confidence(self, s: IndicatorSnapshot, direction: Direction) -> float:
        """Higher when EMAs are well-separated and momentum is strong."""
        spread = abs(s.ema_fast - s.ema_slow) / s.price if s.price else 0.0  # type: ignore[operator]
        momentum = min(abs(s.macd_hist) / (s.atr or 1.0), 1.0)  # type: ignore[operator]
        return round(min(0.55 + spread * 20 + momentum * 0.15, 0.9), 2)
